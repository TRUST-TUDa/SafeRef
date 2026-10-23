"""Regression tests for code-repository citation classification.

Covers the bug where a GitHub (or other code/dataset repo) citation was sent
to academic title-matching and drew a spurious author-mismatch flag. See
_classify_citation_kind in saferef_client/parsing.py.

Run: python -m pytest tests/test_citation_kind.py
(or plain `python tests/test_citation_kind.py` -- no pytest required).
"""

import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from saferef_client.parsing import _classify_citation_kind as classify

_PQM4 = (
    "Matthias J. Kannwischer, Richard Petri, Joost Rijneveld, Peter Schwabe, "
    "and Ko Stoffelen. PQM4: Post-quantum crypto library for the ARM Cortex-M4. "
)

# Must classify as web-resource (never sent to the matching API).
WEB_RESOURCE_CASES = {
    "pqm4 clean https":   _PQM4 + "https://github.com/mupq/pqm4.",
    "pqm4 bare host":     _PQM4 + "github.com/mupq/pqm4.",
    "pqm4 spaced proto":  _PQM4 + "https :// github.com/mupq/pqm4.",
    "pqm4 split newline": _PQM4 + "https://github.\ncom/mupq/pqm4.",
    "pqm4 trailing date": _PQM4 + "https://github.com/mupq/pqm4. Accessed: 2023-01-01.",
    # The real failure mode: PQM4 ref merged with the next (paper) reference.
    "pqm4 merged w/ next": _PQM4 + "https://github.com/mupq/pqm4. Jihoon Jang. "
                           "Efficient Polynomial Multiplication for HQC on ARM "
                           "Cortex-M4. In Proceedings of ICISC, pages 94-108, 2023.",
    "gitlab":             "Foo Bar. Some tool. https://gitlab.com/foo/bar.",
    "huggingface":        "Org. Dataset card. https://huggingface.co/datasets/foo/bar.",
    "github.io pages":    "Foo. Project page. https://foo.github.io/proj/.",
    "plain blog":         "Org. A blog post about X. https://example.com/blog/x.",
}

# Must stay paper (real academic citations, including papers that link code).
PAPER_CASES = {
    "proceedings":        "Jihoon Jang et al. Efficient Polynomial Multiplication "
                          "for HQC on ARM Cortex-M4. In Proceedings of ICISC, "
                          "pages 94-108, 2023.",
    "springer chapter":   "Oscar Reparaz et al. Additively homomorphic ring-LWE "
                          "masking. In Post-Quantum Cryptography, pages 233-244. "
                          "Springer, 2016.",
    "journal vol/issue":  "A. Author. A result. Journal of Cryptology, 12(3) (2021) 45-67.",
    "arxiv id":           "B. Author. A preprint. arXiv:2101.12345, 2021.",
    "arxiv url":          "B. Author. A preprint. https://arxiv.org/abs/2101.12345.",
    "doi + github link":  "C. Author. A real paper with code. In NeurIPS 2021. "
                          "doi:10.1000/xyz. https://github.com/c/code.",
    "doi.org":            "D. Author. Great work. https://doi.org/10.1000/abc.",
    "plain conf no url":  "E. Author. Great work. In Conference on X, 2020.",
}


def test_web_resource_cases():
    for name, text in WEB_RESOURCE_CASES.items():
        assert classify(text) == "web-resource", f"{name!r} should be web-resource"


def test_paper_cases():
    for name, text in PAPER_CASES.items():
        assert classify(text) == "paper", f"{name!r} should be paper"


if __name__ == "__main__":
    failures = 0
    for name, text in WEB_RESOURCE_CASES.items():
        got = classify(text)
        ok = got == "web-resource"
        failures += not ok
        print(f"  [{'OK ' if ok else 'FAIL'}] web-resource  {name:20s} -> {got}")
    for name, text in PAPER_CASES.items():
        got = classify(text)
        ok = got == "paper"
        failures += not ok
        print(f"  [{'OK ' if ok else 'FAIL'}] paper         {name:20s} -> {got}")
    print("\nALL PASS" if not failures else f"\n{failures} FAILED")
    raise SystemExit(1 if failures else 0)
