"""Tests for the web-resource URL reachability check (client.py).

Added alongside the code-repo citation classification fix (see
test_citation_kind.py) -- a web-resource citation was never sent to the
matching API at all, so flagged=False for one meant "not checked", not
"checked and fine", indistinguishable from a real verified citation to a
caller that only looks at `flagged`. check_web_resource_urls (default True)
closes that gap with a cheap HEAD/GET existence check against the cited URL.

URL EXTRACTION tests are pure/offline (just regex + string logic, no
network). REACHABILITY tests make REAL network requests (to github.com,
which is about as close to "always up" as a test dependency gets, and to a
domain that's certain not to resolve) -- these need network access and will
fail offline; that's expected, not a bug in the test.

Run: python -m pytest tests/test_web_resource_url_check.py
(or plain `python tests/test_web_resource_url_check.py` -- no pytest required).
"""

import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from saferef_client.client import _extract_citation_url, _check_url_reachable, verify

# name -> (raw_citation, expected_extracted_url)
EXTRACTION_CASES = {
    "clean url":             ("PQM4. https://github.com/mupq/pqm4.",
                               "https://github.com/mupq/pqm4"),
    "bare host, no proto":   ("Some Tool. github.com/someorg/somerepo, 2023",
                               "https://github.com/someorg/somerepo"),
    "trailing year":         ("A Dataset. https://huggingface.co/datasets/org/name, 2023.",
                               "https://huggingface.co/datasets/org/name"),
    # The real case that broke a naive "stop at whitespace" regex: a PDF
    # line-wrap inserted a space in the middle of the path, not right after
    # the protocol (confirmed on a real citation, mistral7b.pdf's xformers ref).
    "mangled internal space": (
        "xformers library. https://github.com/ facebookresearch/xformers, 2022",
        "https://github.com/facebookresearch/xformers",
    ),
    "no url at all":          ("A. Author. A real paper title. In Conference, 2020.", None),
}


def test_extraction_cases():
    for name, (raw, expected) in EXTRACTION_CASES.items():
        got = _extract_citation_url(raw)
        assert got == expected, f"{name!r}: got {got!r}, expected {expected!r}"


def test_reachable_real_url():
    # github.com itself, not a specific repo -- avoids the test depending on
    # some third party's repo never being deleted/renamed.
    assert _check_url_reachable("https://github.com/") is True


def test_unreachable_fake_domain():
    assert _check_url_reachable("https://this-domain-will-never-exist-saferef-test.invalid/") is False


def test_none_url_is_inconclusive():
    assert _check_url_reachable(None) is None


def test_end_to_end_flags_fabricated_web_resource():
    fake = {
        "citation_id":   1,
        "raw_citation":  "J. Doe. FakeTool. https://this-domain-will-never-exist-saferef-test.invalid/, 2024",
        "parsed_title":  "FakeTool",
        "parsed_authors": ["J. Doe"],
        "citation_kind": "web-resource",
    }
    result = verify([fake])[0]
    assert result["title_status"] == "web-resource"
    assert result["url_reachable"] is False
    assert result["flagged"] is True


def test_opt_out_skips_the_check():
    fake = {
        "citation_id":   1,
        "raw_citation":  "J. Doe. FakeTool. https://this-domain-will-never-exist-saferef-test.invalid/, 2024",
        "parsed_title":  "FakeTool",
        "parsed_authors": ["J. Doe"],
        "citation_kind": "web-resource",
    }
    result = verify([fake], check_web_resource_urls=False)[0]
    assert result["url_reachable"] is None
    assert result["flagged"] is False


if __name__ == "__main__":
    failures = 0

    print("-- URL extraction (offline) --")
    for name, (raw, expected) in EXTRACTION_CASES.items():
        got = _extract_citation_url(raw)
        ok = got == expected
        failures += not ok
        print(f"  [{'OK ' if ok else 'FAIL'}] {name:25s} -> {got!r}")

    print("-- Reachability + end-to-end (needs network) --")
    for name, fn in [
        ("real url (github.com)", test_reachable_real_url),
        ("fake domain", test_unreachable_fake_domain),
        ("none url", test_none_url_is_inconclusive),
        ("end-to-end flags fabricated", test_end_to_end_flags_fabricated_web_resource),
        ("opt-out skips check", test_opt_out_skips_the_check),
    ]:
        try:
            fn()
            print(f"  [OK ] {name}")
        except AssertionError as e:
            failures += 1
            print(f"  [FAIL] {name}: {e}")

    print("\nALL PASS" if not failures else f"\n{failures} FAILED")
    raise SystemExit(1 if failures else 0)
