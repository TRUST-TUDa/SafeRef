"""
authors.py

Client-side author-list comparison -- used when the caller chooses not to
send `authors` to the API at all (client.verify(..., send_authors=False)),
to keep the request smaller/cheaper without losing author verification.
The server already returns `db_authors` for every match regardless of
whether authors were sent, so this just does the same comparison locally
using citation data the library already has.

Copy of server/matching.py's AuthorCheck normalization logic, kept in sync
by hand -- SafeRef's convention for anything shared across library/ and
server/ is a self-contained copy, not a cross-import.
"""
import re

_SURNAME_PREFIXES = {
    "van", "von", "de", "del", "della", "di", "da", "al", "el", "la",
    "le", "ben", "ibn", "mac", "mc", "o",
}
_NAME_SUFFIXES = {"jr", "sr", "ii", "iii", "iv", "v"}
_AUTHOR_SPLIT_RE = re.compile(r"\s*;\s*|\s*,\s*|\s+and\s+|\s*&\s*", re.IGNORECASE)
# DBLP appends a bare numeric disambiguator as its own token when multiple
# people share a name, e.g. "Francesco Santini 0001" -- a real citation
# would never write an author name this way, so stripping it before
# comparison is safe on both sides and fixes DBLP-merged records scoring
# "partial" instead of "exact" purely because of this DBLP-only convention.
_DBLP_DISAMBIGUATOR_RE = re.compile(r"\s+\d+$")


def _normalize_space(text: str) -> str:
    return re.sub(r"\s+", " ", str(text or "")).strip()


def _surname_from_parts(parts: list[str]) -> str:
    if not parts:
        return ""
    while len(parts) >= 2 and parts[-1].lower().rstrip(".") in _NAME_SUFFIXES:
        parts = parts[:-1]
    if len(parts) >= 3 and parts[-3].lower().rstrip(".") in _SURNAME_PREFIXES:
        return " ".join(parts[-3:])
    if len(parts) >= 2 and parts[-2].lower().rstrip(".") in _SURNAME_PREFIXES:
        return " ".join(parts[-2:])
    return parts[-1]


def _normalize_author(name: str) -> str:
    name = _normalize_space(name)
    name = _DBLP_DISAMBIGUATOR_RE.sub("", name).strip()
    if not name:
        return ""
    if "," in name:
        surname, _, initials = name.partition(",")
        surname = surname.strip().lower()
        initials = initials.strip()
        first_initial = initials[0].lower() if initials else ""
        return f"{first_initial} {surname}".strip()
    parts = [part for part in name.split() if part]
    if not parts:
        return ""
    surname = _surname_from_parts(parts).lower()
    first_initial = parts[0][0].lower()
    return f"{first_initial} {surname}".strip()


def compare_authors(parsed_authors: list[str], db_authors: list[str]) -> tuple[str, float]:
    """Same decision logic as server/matching.py's AuthorCheck._evaluate():
    returns (verdict, score) with verdict in "unknown"/"exact"/"partial"/"mismatch".
    db_authors here is already a list of names (e.g. from an API result's
    "db_authors" field) -- no splitting needed, unlike the server's version
    which splits a raw db string."""
    parsed_normalized = {_normalize_author(a) for a in parsed_authors if _normalize_author(a)}
    db_normalized = {_normalize_author(a) for a in db_authors if _normalize_author(a)}
    if not parsed_normalized or not db_normalized:
        return "unknown", 0.5
    matched = parsed_normalized & db_normalized
    overlap = len(matched) / max(1, len(parsed_normalized))
    if overlap >= 1:
        return "exact", 1.0
    if overlap > 0.0:
        return "partial", 0.65
    return "mismatch", 0.0
