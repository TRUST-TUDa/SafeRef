"""
titles.py

Client-side title-match comparison -- compares a citation's own parsed
title against the title of whatever record the server matched it to
(`matched_title`, which the API always returns alongside a title match),
so that title-fake detection and its flagging policy live in the library
rather than being a single hardcoded toggle on the server for every caller.

Copy of server/matching.py's normalize_title, kept in sync by hand --
SafeRef's convention for anything shared across library/ and server/ is a
self-contained copy, not a cross-import.
"""
import re
import unicodedata
from difflib import SequenceMatcher

_WS_RE = re.compile(r"\s+")
_LATEX_BRACE_RE = re.compile(r"[{}]")
_LATEX_ACCENT_RE = re.compile(r"\\[\"'`^~][a-zA-Z]")


def normalize_title(title: str) -> str:
    if not title:
        return ""
    t = title.strip()
    t = t.replace("\n", " ")
    t = _LATEX_ACCENT_RE.sub(lambda m: m.group(0)[-1], t)
    t = _LATEX_BRACE_RE.sub("", t)
    t = unicodedata.normalize("NFKC", t)
    t = t.lower()
    t = re.sub(r"[^\w\s\-]", " ", t)
    t = _WS_RE.sub(" ", t).strip()
    return t


def compare_titles(parsed_title: str | None, matched_title: str | None) -> tuple[bool | None, float | None]:
    """
    Compare a citation's own parsed title against the title of whichever
    record the server matched it to.

    Returns (exact_match, similarity):
        exact_match: True/False, or None if there's nothing to compare
            (no match found, or no parsed title) -- same "unknown, don't
            guess" convention as compare_authors()'s "unknown" verdict.
        similarity: difflib.SequenceMatcher's ratio() on the two normalized
            titles, in [0.0, 1.0], or None under the same condition.

    Real measured context for interpreting this (see project history):
    pure embedding similarity alone is a weak fake-title detector at this
    corpus's scale (~98% of fabricated titles in one benchmark still scored
    above the verification threshold). Requiring an EXACT normalized-title
    match is a much stronger signal (drops that false-positive rate to
    ~5%, and even that residual turned out to mostly be benchmark-labeling
    noise, not real misses) -- but it also incorrectly flags a real ~7% of
    genuinely correct citations (formatting/OCR noise in the parsed title).
    `similarity` is offered as additional context for exactly that
    ambiguous middle ground, not as a separate pass/fail threshold -- a
    fuzzy cutoff was tested as a hard gate and found to not meaningfully
    beat plain exact-match on that same tradeoff, so treat it as
    informational, not as "similarity >= X means real."
    """
    if not parsed_title or not matched_title:
        return None, None
    a = normalize_title(parsed_title)
    b = normalize_title(matched_title)
    if not a or not b:
        return None, None
    return a == b, round(SequenceMatcher(None, a, b).ratio(), 4)
