"""
client.py

extract citations from a PDF (parsing.py's Parser, zero ML deps) and ask
the SafeRef API whether each one verifies:
verify_pdf(pdf_path, api_url) -> a list of per-citation verdicts.

"web-resource" citations (blog posts, product pages, dataset cards, ...)
are never sent to the API -- they get their own title_status locally
instead of costing a network round trip.
"""

from __future__ import annotations

import requests

from .authors import compare_authors
from .parsing import Parser
from .titles import compare_titles

DEFAULT_TIMEOUT = 120

# The project's own public instance -- override with your own api_url if you're
# running a different server.
DEFAULT_API_URL = "https://saferef.trust.informatik.tu-darmstadt.de:60301"

# Requests larger than this are chunked into sequential sub-requests.
MAX_BATCH_SIZE = 100


def extract_citations(pdf_path: str) -> list[dict]:
    """Parse a PDF into citation records. No network calls."""
    return Parser(pdf_path).records


def verify(
    citations: list[dict],
    api_url: str = DEFAULT_API_URL,
    api_key: str | None = None,
    timeout: float = DEFAULT_TIMEOUT,
    send_authors: bool = True,
    flag_on_title_mismatch: bool = False,
) -> list[dict]:
    """
    Send parsed citations to the SafeRef API for title verification, then
    apply author/title comparison and flagging policy locally.

    Args:
        citations: records as returned by extract_citations() / Parser.
        api_url:   base URL of the SafeRef API. Defaults to the project's own
            public instance; pass your own if you're running a different server.
        api_key:   sent as "Authorization: Bearer <api_key>" if given.
        timeout:   per-request timeout in seconds, applied to each chunk.
        send_authors: if False, author names aren't sent to the server;
            author_status is still computed locally either way from the
            `db_authors` the API always returns.
        flag_on_title_mismatch: if True, adds "title text does not exactly
            match matched record" to flag_reasons when title_exact_match is
            False. Default False -- catches ~95% of fabricated titles but
            also flags ~7% of real citations (parsing/OCR noise); off by
            default so callers can apply their own threshold instead via
            title_exact_match/title_similarity.

    Returns:
        One result dict per citation sent:
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
    api_url: str = DEFAULT_API_URL,
    api_key: str | None = None,
    timeout: float = DEFAULT_TIMEOUT,
    send_authors: bool = True,
    flag_on_title_mismatch: bool = False,
) -> list[dict]:
    """One-call convenience: extract + verify, merged into one row per
    citation (parsed fields + verdict fields)."""
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


def verify_titles(
    titles: str | list[str],
    api_url: str = DEFAULT_API_URL,
    authors: list[str] | list[list[str]] | None = None,
    api_key: str | None = None,
    timeout: float = DEFAULT_TIMEOUT,
    send_authors: bool = True,
    flag_on_title_mismatch: bool = False,
) -> dict | list[dict]:
    """
    One-call convenience for verifying titles you already have -- from a
    spreadsheet, a different parser, manual entry -- without needing a PDF.
    Same underlying call as verify_pdf(), just skipping extract_citations().

    titles: a single title, or a list of titles.
    authors: optional, matching titles' shape:
        - titles is a single str -> a flat list of author name strings.
        - titles is a list -> a list of one author-list per title, same
          length as titles. Use [] for a title with no known authors --
          don't just shorten the list.
        Omit entirely if you have no author info for any of them.

    Returns a single merged result dict if titles was a single string,
    otherwise a list of them in the same order as titles -- same row shape
    as verify_pdf(): {citation_id, parsed_title, parsed_authors,
    title_status, matched_source, match_score, matched_title,
    author_status, db_authors, title_exact_match, title_similarity,
    flagged, flag_reasons}.
    """
    single = isinstance(titles, str)
    title_list = [titles] if single else list(titles)

    if authors is None:
        author_lists = [[] for _ in title_list]
    elif single:
        author_lists = [list(authors)]
    else:
        author_lists = [list(a) if a else [] for a in authors]
        if len(author_lists) != len(title_list):
            raise ValueError(f"authors has {len(author_lists)} entries, titles has {len(title_list)}")

    citations = [
        {"citation_id": i, "parsed_title": t, "parsed_authors": a}
        for i, (t, a) in enumerate(zip(title_list, author_lists))
    ]

    results_by_id = {
        r["citation_id"]: r
        for r in verify(citations, api_url, api_key, timeout, send_authors, flag_on_title_mismatch)
    }
    merged = []
    for c in citations:
        row = dict(c)
        row.update(results_by_id.get(c["citation_id"], {}))
        merged.append(row)

    return merged[0] if single else merged
