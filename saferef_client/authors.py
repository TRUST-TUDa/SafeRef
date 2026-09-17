"""
authors.py

Client-side author-list comparison, used to compute author_status locally
regardless of whether author names were sent to the API.
"""
import re

_SURNAME_PREFIXES = {
    "van", "von", "de", "del", "della", "di", "da", "al", "el", "la",
    "le", "ben", "ibn", "mac", "mc", "o",
}
_NAME_SUFFIXES = {"jr", "sr", "ii", "iii", "iv", "v"}
_AUTHOR_SPLIT_RE = re.compile(r"\s*;\s*|\s*,\s*|\s+and\s+|\s*&\s*", re.IGNORECASE)
# Strips DBLP's numeric disambiguator, e.g. "Francesco Santini 0001".
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
    """Returns (verdict, score), verdict in "unknown"/"exact"/"partial"/"mismatch"."""
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
