"""
client.py

The "black box" side of the client library: extract citations from a PDF
(parsing.py's Parser, zero ML deps) and ask the SafeRef API whether each one
verifies. Callers never see FAISS/SPECTER2/Crossref -- just
verify_pdf(pdf_path, api_url) -> a list of per-citation verdicts.

"web-resource" citations (blog posts, product pages, dataset cards, ...) are
never sent to the API -- Parser already classified them structurally, and
they were never going to be in an academic index, so a non-match wouldn't
mean anything. They get their own title_status locally instead of costing a
network round trip.
"""

from __future__ import annotations

import requests

from .authors import compare_authors
from .parsing import Parser
from .titles import compare_titles

DEFAULT_TIMEOUT = 120

# Mirrors server/app.py's MAX_BATCH_SIZE. Kept in sync by hand (copy, not
# import, per this repo's convention -- the server and this library are
# separate deployable units). If a caller passes more citations than this in
# one verify() call, they're chunked into sequential sub-requests instead of
# one oversized request the server would reject with a 413.
MAX_BATCH_SIZE = 100


def extract_citations(pdf_path: str) -> list[dict]:
    """Parse a PDF into citation records (see parsing.Parser for the full
    per-record schema). No network calls."""
    return Parser(pdf_path).records


def verify(
    citations: list[dict],
    api_url: str,
    api_key: str | None = None,
    timeout: float = DEFAULT_TIMEOUT,
    send_authors: bool = True,
    flag_on_title_mismatch: bool = False,
) -> list[dict]:
    """
    Send parsed citations to the SafeRef API for title verification, then
    apply this library's own author-comparison, title-comparison, and
    flagging policy locally -- the server does the heavy FAISS/database
    matching and returns raw data (matched_title, db_authors, scores); the
    library owns the decision of what that data means for the caller, so
    that policy can evolve (or be overridden per-call) without needing a
    server change or a server-wide toggle affecting every caller at once.

    Args:
        citations: records as returned by extract_citations() / Parser --
            only "citation_id", "parsed_title", and "parsed_authors" are
            used; the rest of each record is ignored by the API.
        api_url:   base URL of the SafeRef API, e.g. "https://api.example.com"
        api_key:   sent as "Authorization: Bearer <api_key>" if given.
        timeout:   per-request timeout in seconds, applied to EACH chunk (see
            below), not the call as a whole. The server resolves citations
            synchronously (arXiv is fast; a Crossref fallback can take tens
            of seconds per citation still needing it), so a batch with many
            Crossref misses can take a while -- raise this for large batches
            rather than lowering it.
        send_authors: if False, `authors` is left out of the request entirely
            (smaller request, nothing for the server to compare). Doesn't
            change the result: author_status is always computed locally by
            this function regardless of send_authors (see below), using the
            `db_authors` the API always returns alongside a title match --
            send_authors only controls whether parsed author names leave
            the caller's machine at all, a privacy knob, not an accuracy one.
        flag_on_title_mismatch: if True, a citation whose parsed title isn't
            an EXACT normalized-text match to the matched record's title
            (title_exact_match is False) adds "title text does not exactly
            match matched record" to flag_reasons. Default False because
            this specific check has a real measured cost: in testing, it
            correctly caught ~95% of genuinely fabricated titles but also
            incorrectly flagged ~7% of real, correct citations (parsing/OCR
            noise) -- see compare_titles()'s docstring. Left off by default
            so a caller isn't silently opted into that false-positive rate;
            title_exact_match/title_similarity are always still returned so
            a caller can apply their own threshold instead.

    The server caps a single request at MAX_BATCH_SIZE citations. Anything
    larger than that here is chunked into sequential sub-requests
    automatically -- callers never need to think about this limit or split
    a big reference list themselves.

    Returns:
        One result dict per *paper* citation sent (web-resource citations are
        filtered out before the request and re-attached below), each:
        {citation_id, title_status, matched_source, match_score,
         matched_title, author_status, db_authors, title_exact_match,
         title_similarity, flagged, flag_reasons}.
    """
    web_resource_results = [
        {
            "citation_id":       c["citation_id"],
            "title_status":      "web-resource",
            "matched_source":    "none",
            "match_score":       None,
            "matched_title":     None,
            "author_status":     "N/A",
            "db_authors":        [],
            "title_exact_match": None,
            "title_similarity":  None,
            "flagged":           False,
            "flag_reasons":      [],
        }
        for c in citations
        if c.get("citation_kind") == "web-resource"
    ]
    paper_citations = [c for c in citations if c.get("citation_kind") != "web-resource"]
    payload_citations = [
        {
            "citation_id": c["citation_id"],
            "title":       c.get("parsed_title") or "",
            **({"authors": c.get("parsed_authors") or []} if send_authors else {}),
        }
        for c in paper_citations
    ]

    # The server caps requests at MAX_BATCH_SIZE citations (a latency/fairness
    # limit, not a correctness one -- see server/app.py's own comment on it).
    # Chunked sequentially, not concurrently: this is a single long-lived
    # server process with no cross-request queueing yet, so firing chunks in
    # parallel would just contend with itself for the same GPU/FAISS/DB
    # resources rather than actually going faster.
    api_results = []
    if payload_citations:
        headers = {"Authorization": f"Bearer {api_key}"} if api_key else {}
        for start in range(0, len(payload_citations), MAX_BATCH_SIZE):
            chunk = payload_citations[start:start + MAX_BATCH_SIZE]
            resp = requests.post(
                f"{api_url.rstrip('/')}/v1/citations/verify",
                json={"citations": chunk},
                headers=headers,
                timeout=timeout,
            )
            resp.raise_for_status()
            api_results.extend(resp.json()["results"])

    parsed_by_id = {c["citation_id"]: c for c in paper_citations}
    for r in api_results:
        parsed = parsed_by_id.get(r["citation_id"], {})

        # Author comparison always runs here, regardless of send_authors --
        # this library owns author-mismatch flagging, not the server. Same
        # algorithm either way; send_authors only affects whether names were
        # also sent for the server's own (now-superseded) computation.
        verdict, _score = compare_authors(parsed.get("parsed_authors") or [], r.get("db_authors") or [])
        r["author_status"] = verdict

        exact_match, similarity = compare_titles(parsed.get("parsed_title"), r.get("matched_title"))
        r["title_exact_match"] = exact_match
        r["title_similarity"] = similarity

        reasons = []
        if r.get("title_status") not in ("verified", "web-resource"):
            reasons.append("title not verified")
        if r["author_status"] == "mismatch":
            reasons.append("author mismatch")
        if flag_on_title_mismatch and exact_match is False:
            reasons.append("title text does not exactly match matched record")
        r["flag_reasons"] = reasons
        r["flagged"] = bool(reasons)

    return sorted(api_results + web_resource_results, key=lambda r: r["citation_id"])


def verify_pdf(
    pdf_path: str,
    api_url: str,
    api_key: str | None = None,
    timeout: float = DEFAULT_TIMEOUT,
    send_authors: bool = True,
    flag_on_title_mismatch: bool = False,
) -> list[dict]:
    """One-call convenience: extract + verify, merged into one row per
    citation (parsed fields + verdict fields). This is the function most
    callers want -- extract_citations()/verify() are there for anyone who
    needs to inspect or filter the parsed citations before sending them."""
    citations = extract_citations(pdf_path)
    results_by_id = {
        r["citation_id"]: r
        for r in verify(citations, api_url, api_key, timeout, send_authors, flag_on_title_mismatch)
    }

    merged = []
    for c in citations:
        row = dict(c)
        row.update(results_by_id.get(c["citation_id"], {}))
        merged.append(row)
    return merged
