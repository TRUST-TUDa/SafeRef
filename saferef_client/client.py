"""
client.py

extract citations from a PDF (parsing.py's Parser, zero ML deps) and ask
the SafeRef API whether each one verifies:
verify_pdf(pdf_path, api_url) -> a list of per-citation verdicts.

"web-resource" citations (blog posts, product pages, dataset cards, ...)
are never sent to the API -- they get their own title_status locally.
They still get a real, independent check by default though: a cheap
HEAD/GET request straight to the cited URL confirms it still exists,
since "not sent to the API" previously meant no check of any kind,
leaving a fabricated or dead web-resource citation indistinguishable
from a legitimate one (see check_web_resource_urls on verify()/verify_pdf()).
"""

from __future__ import annotations

import concurrent.futures
import re

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

# How many web-resource URLs to check concurrently -- these are independent,
# I/O-bound network calls, so a small thread pool keeps the check fast even
# when a paper cites several code/dataset repos, without hammering too many
# different external hosts at once.
_URL_CHECK_WORKERS = 8
_URL_CHECK_TIMEOUT = 5.0

# Finds where a fetchable URL STARTS inside a raw citation string -- separate
# from parsing.py's classification regexes (which only need to detect THAT a
# URL/host is present, not extract the full string to request it). A PDF
# line-wrap can insert a stray space ANYWHERE in a URL, not just right after
# the protocol (confirmed on a real citation: "https://github.com/
# facebookresearch/xformers") -- so unlike a normal "stop at whitespace" URL
# regex, extraction below spans to a citation-ending marker instead and
# strips whitespace from within that span, rather than stopping at the
# first stray space and silently truncating the path.
_URL_START_RE = re.compile(r"https?\s*:\s*//\s*|www\.", re.IGNORECASE)
_BARE_CODE_HOST_START_RE = re.compile(
    r"\b(?:github\.com|gitlab\.com|bitbucket\.org|sourceforge\.net|codeberg\.org|"
    r"gitee\.com|huggingface\.co|[A-Za-z0-9-]+\.github\.io)/",
    re.IGNORECASE,
)
# The overwhelmingly common way a URL ends in a reference list: ", <year>".
# Used as the span's end marker when present, since a bare whitespace-based
# cutoff can't be used (see above) -- falls back to the end of the string.
_CITATION_URL_END_RE = re.compile(r",\s*(?:19|20)\d{2}\b")


def _extract_citation_url(raw_citation: str | None) -> str | None:
    """Best-effort extraction of a fetchable URL from a raw citation string,
    for the reachability check below. Returns None (skip the check) rather
    than guess if nothing confidently URL-shaped is found."""
    if not raw_citation:
        return None
    m = _URL_START_RE.search(raw_citation) or _BARE_CODE_HOST_START_RE.search(raw_citation)
    if not m:
        return None
    rest = raw_citation[m.start():]
    end = _CITATION_URL_END_RE.search(rest)
    url_span = rest[:end.start()] if end else rest
    url = re.sub(r"\s+", "", url_span)  # collapse PDF-mangled internal spaces (can occur anywhere, not just after the protocol)
    url = url.rstrip(".,;:)]")  # trailing sentence punctuation, not part of the URL
    if not url.lower().startswith(("http://", "https://")):
        url = "https://" + url
    return url


def _check_url_reachable(url: str | None) -> bool | None:
    """Cheap existence check -- HEAD request, falling back to GET only if the
    server actively rejects HEAD (405/501: it's there, it just doesn't like
    that method -- a connection-level failure means GET would fail the same
    way, so no fallback attempt in that case). Never downloads the response
    body either way -- this confirms the resource exists, it doesn't inspect
    its content.

    Deliberately conservative about what counts as "unreachable" (False),
    since a caller may act on this (e.g. flagging the citation) and a false
    positive on a real, legitimate resource is worse than missing a genuine
    fabrication: only a clear 404/410 (the server positively says this
    specific resource is gone) or a DNS/connection failure (the host itself
    doesn't resolve or respond) count. A 403/429/5xx or a timeout is about
    access or server health, not evidence the resource doesn't exist, so
    those return None (inconclusive) rather than False.
    """
    if not url:
        return None
    headers = {"User-Agent": "Mozilla/5.0 (compatible; SafeRefCitationCheck/1.0; "
                              "+https://github.com/TRUST-TUDa/SafeRef)"}
    try:
        resp = requests.head(url, timeout=_URL_CHECK_TIMEOUT, allow_redirects=True, headers=headers)
        if resp.status_code in (405, 501):
            resp = requests.get(url, timeout=_URL_CHECK_TIMEOUT, allow_redirects=True,
                                 headers=headers, stream=True)
            resp.close()
        if resp.status_code in (404, 410):
            return False
        if resp.status_code < 400:
            return True
        return None
    except requests.exceptions.Timeout:
        return None
    except requests.exceptions.ConnectionError:
        return False
    except requests.exceptions.RequestException:
        return None


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
    check_web_resource_urls: bool = True,
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
        check_web_resource_urls: a "web-resource" citation (a code repo,
            dataset card, blog post, ...) is never sent to the API, so
            without this it gets no check of any kind -- flagged=False
            either way, which could read as "checked and fine" when really
            nothing was checked at all. Default True: does a cheap HEAD
            request (GET fallback, no body downloaded) against the cited
            URL and flags it if the URL is clearly gone (404/410) or the
            host doesn't resolve/respond. Not sending citation titles to a
            second party, unlike send_authors -- this only contacts the URL
            the citation itself already points to, and verify_pdf() already
            requires network access to reach the SafeRef API, so this adds
            no new category of network exposure, just more of it. Set False
            to skip it (e.g. fully offline use, or if the extra requests
            aren't wanted).

    Returns:
        One result dict per citation sent:
        {citation_id, title_status, matched_source, match_score,
         matched_title, author_status, db_authors, title_exact_match,
         title_similarity, url_reachable, flagged, flag_reasons}.
        url_reachable is True/False/None for a web-resource citation (None
        if checking was skipped or inconclusive), always None for a paper
        citation (not applicable).
    """
    web_resource_citations = [c for c in citations if c.get("citation_kind") == "web-resource"]
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
            "url_reachable":     None,
            "flagged":           False,
            "flag_reasons":      [],
        }
        for c in web_resource_citations
    ]

    if check_web_resource_urls and web_resource_citations:
        urls = [_extract_citation_url(c.get("raw_citation")) for c in web_resource_citations]
        with concurrent.futures.ThreadPoolExecutor(max_workers=min(_URL_CHECK_WORKERS, len(urls))) as pool:
            reachable_flags = list(pool.map(_check_url_reachable, urls))
        for result, reachable in zip(web_resource_results, reachable_flags):
            result["url_reachable"] = reachable
            if reachable is False:
                result["flagged"] = True
                result["flag_reasons"] = [
                    "cited URL appears unreachable (page not found or host does not respond) -- "
                    "the resource may have been removed, moved, or never existed"
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
            reasons.append("no confident title match found in our corpus")
        if r["author_status"] == "mismatch":
            if similarity is not None and similarity < 0.85:
                reasons.append(
                    "authors don't match the nearest title candidate, and that candidate's "
                    "title itself looks substantially different, this usually means the "
                    "cited paper isn't in our corpus (e.g. an unindexed workshop paper), not "
                    "that its authors were fabricated"
                )
            else:
                reasons.append("authors don't match the matched paper's actual author list")
        if flag_on_title_mismatch and exact_match is False:
            reasons.append("title text does not exactly match matched record")
        r["flag_reasons"] = reasons
        r["flagged"] = bool(reasons)
        r["url_reachable"] = None  # not applicable to a paper citation -- see web-resource results above

    return sorted(api_results + web_resource_results, key=lambda r: r["citation_id"])


def verify_pdf(
    pdf_path: str,
    api_url: str = DEFAULT_API_URL,
    api_key: str | None = None,
    timeout: float = DEFAULT_TIMEOUT,
    send_authors: bool = True,
    flag_on_title_mismatch: bool = False,
    check_web_resource_urls: bool = True,
) -> list[dict]:
    """One-call convenience: extract + verify, merged into one row per
    citation (parsed fields + verdict fields). See verify()'s docstring for
    check_web_resource_urls."""
    citations = extract_citations(pdf_path)
    results_by_id = {
        r["citation_id"]: r
        for r in verify(citations, api_url, api_key, timeout, send_authors, flag_on_title_mismatch,
                         check_web_resource_urls)
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
