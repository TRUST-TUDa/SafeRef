# Fix: code-repository citations wrongly sent to title-matching

**Branch:** `fix/github-repo-citation-classification`
**Files changed:** `saferef_client/parsing.py`, `tests/test_citation_kind.py` (new)
**Scope:** client-side citation classification only. No server change, no API change, no public interface change.

---

## The bug (as reported)

A citation to a GitHub software repository was being sent to academic
title-matching instead of being excluded as a non-academic web resource. The
spurious title-embedding match that resulted produced a false **author-mismatch
flag**.

Real recurring example (two Kyber side-channel papers under submission):

> Matthias J. Kannwischer, Richard Petri, Joost Rijneveld, Peter Schwabe, and
> Ko Stoffelen. PQM4: Post-quantum crypto library for the ARM Cortex-M4.
> https://github.com/mupq/pqm4.

Title was extracted correctly (`PQM4: ...`) but matched to the unrelated paper
*"Efficient Polynomial Multiplication for HQC on ARM Cortex-M4"* (shares only
"ARM Cortex-M4"), yielding a bogus author mismatch.

The original PDFs could not be shared, so this was reproduced from the
verification report text plus a **synthetic test PDF** built to exercise the
full parse pipeline.

## Root cause

`_classify_citation_kind()` already excludes web resources, and on the *clean,
isolated* PQM4 string it returned `web-resource` correctly. The real-world
failures come from two input shapes it did **not** handle:

1. **Segmentation merge (primary cause).** When the PQM4 reference gets
   concatenated with the following reference (a common failure in back-to-back,
   markerless bibliography styles), the classifier saw the *neighbour's*
   paper-markers (`Proceedings`, `Springer`, `pages`, year) and flipped the
   whole record to `paper`. The record's title stayed `PQM4` (correct), so it
   looked fine but was sent to matching anyway.
2. **URL not recognised.** The URL regex only matched `https?://` / `www.`, so a
   bare `github.com/...` (no protocol) or a PDF-extraction artifact like
   `https :// github.com/...` (protocol split off) was not seen as a URL at all
   → defaulted to `paper`.

## The fix

In `_classify_citation_kind()` (`saferef_client/parsing.py`):

- Added `_CITATION_CODE_REPO_RE` matching code/dataset hosts — github, gitlab,
  bitbucket, sourceforge, codeberg, gitee, huggingface, `*.github.io` — with the
  **protocol optional** and a trailing `/` required (so a real repo path is
  present; a stray "github" in prose won't match).
- A matched repo URL is now a **decisive web-resource signal** that overrides
  the generic paper-markers. This is what fixes the merge case.
- Pulled the arXiv check out into `_CITATION_ARXIV_RE` and run it (with the
  existing DOI check) **before** the repo check, so formal registration still
  wins: a real paper/preprint that merely links its code on GitHub stays a
  `paper` and remains verifiable.

New precedence: `DOI → arXiv → code-repo → (generic URL & no paper-marker) → paper`.

### Known trade-off (please review)

A citation that has a bare repo URL **and no DOI/arXiv** but is genuinely a
published paper will now be classified `web-resource` and skipped for
verification. Judged acceptable because (a) such papers almost always carry a
DOI or arXiv id, which win first, and (b) a missed verification is a safer
failure than the current bug's *actively misleading* false author-mismatch flag
on a correct citation. Flag it if you'd prefer this tightened (e.g. require the
repo URL to be the citation's terminal token).

---

## How to test

From the repo root on this branch:

```bash
python tests/test_citation_kind.py      # standalone, no pytest needed
# or
python -m pytest tests/test_citation_kind.py
```

Expected: **ALL PASS** — 10 web-resource cases (the PQM4 example and its real
degradations: bare host, spaced protocol, newline-split URL, trailing "Accessed"
date, and the merged-with-next-reference blob; plus gitlab / huggingface /
github.io / plain blog) and 8 regression cases that must stay `paper`
(proceedings, Springer chapter, journal vol/issue, arXiv id + url,
DOI-with-github-link, doi.org, plain conference).

**End-to-end against a real PDF (recommended, since the group has the real
papers):** run the normal `verify_pdf()` flow on a PDF whose reference list
contains a bare-GitHub-URL citation and confirm that citation comes back with
`title_status: "web-resource"` (i.e. it is *not* sent to the API and carries no
author-mismatch flag). The classification change only affects which citations
are forwarded; everything downstream is unchanged.

## How to integrate

```bash
git fetch origin
git checkout fix/github-repo-citation-classification

# review
git diff main..fix/github-repo-citation-classification

# merge to main when satisfied
git checkout main
git merge --no-ff fix/github-repo-citation-classification
git push origin main
```

Or open a PR: `gh pr create --base main --head fix/github-repo-citation-classification`.

The diff is small and self-contained (one function + its regexes, plus a new
test file). Nothing else in the parse pipeline or the client API was touched.

---

*Note:* this same fix was developed and verified first in the local `library/`
copy, then ported here. The two copies differ only in comments/docstrings; the
executable change is identical.
