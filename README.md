# SafeRef

**Extract academic citations from PDFs and verify them against trusted scholarly indexes.**

SafeRef is a lightweight Python client for extracting references from academic PDFs and checking whether those references can be matched to records in **arXiv** and **Crossref** through the SafeRef API.

The library handles the local work, PDF parsing, citation extraction, and result formatting. 
While the SafeRef API performs the title and author matching.

> **SafeRef is a verification aid, not a truth detector.**
>
> A citation reported as `not-verified` is **not proof that the paper is fake or nonexistent**. The citation may have been parsed incorrectly, the title may differ substantially from the indexed version, or the work may simply not be present in arXiv or Crossref. Treat SafeRef results as signals for further investigation, not definitive judgments.

------

## How it works

SafeRef follows a simple pipeline:

```text
      Academic PDF
           │
           ▼
┌─────────────────────┐
│ Citation extraction │
└──────────┬──────────┘
           │
           ▼
┌─────────────────────┐
│ SafeRef API         │
│                     │
│ • title matching    │
│ • author matching   │
│ • source detection  │
└──────────┬──────────┘
           │
           ▼
   Verification results
```

The Python library **does not contain an ML model or academic database**. It extracts citations locally and sends the relevant information to a running SafeRef API server.

The API compares citations against supported scholarly sources, currently:

* **arXiv**
* **Crossref**

Non-academic web resources such as blog posts and product pages are identified separately and are not sent to the academic verification API.

---

## Installation

Clone the repository and install the library's dependencies:

```bash
git clone https://github.com/<org>/SafeRef.git
cd SafeRef/library

pip install -r requirements.txt
```

SafeRef has deliberately minimal client-side dependencies. The library only needs the components required for:

* PDF parsing
* citation extraction
* HTTP communication with the SafeRef API

**Title and author matching happens server-side.**

> Replace `<org>` with the GitHub organization or username hosting your SafeRef repository.

---

## Quick start

Once you have a SafeRef API server running, verifying a PDF takes only a few lines:

```python
from saferef_client import verify_pdf

results = verify_pdf(
    "paper.pdf",
    api_url="https://api.example.com",
)

for result in results:
    print(
        result["citation_id"],
        result["title_status"],
        result["author_status"],
        result["parsed_title"],
    )
```

`api_url` must point to a running SafeRef API deployment.

A public SafeRef API instance can be documented here once one is available. Until then, use your own deployment.

---

## Understanding the results

`verify_pdf()` returns one result for each extracted citation.

Each result combines:

1. **what SafeRef extracted from the PDF**, and
2. **what the SafeRef API found when checking that citation**.

### Result fields

| Field               | Description                                                              |
| ------------------- | ------------------------------------------------------------------------- |
| `citation_id`       | Identifier assigned to the extracted citation                             |
| `parsed_title`      | Title extracted from the PDF                                              |
| `parsed_authors`    | Authors extracted from the PDF                                            |
| `title_status`      | Result of title verification                                              |
| `matched_source`    | Source containing the matching record                                     |
| `match_score`       | Similarity score for the matched title, when available                   |
| `matched_title`     | The title text of the matched record, when available                     |
| `author_status`     | Result of comparing the citation's authors with the matched record        |
| `db_authors`        | Authors associated with the matched database record                       |
| `title_exact_match` | Whether `parsed_title` and `matched_title` are identical after normalizing (`True`/`False`/`None`) |
| `title_similarity`  | Fuzzy similarity (0.0-1.0) between the normalized titles, when available |
| `flagged`           | `True` if any concern was raised about this citation                      |
| `flag_reasons`      | List of short strings explaining why `flagged` is `True` (empty otherwise) |

`author_status`, `title_exact_match`, `title_similarity`, `flagged`, and `flag_reasons` are all computed **locally by the library**, not by the server — the server only performs the FAISS search and returns raw data (`matched_title`, `db_authors`, scores). This means the comparison/flagging policy lives in the library, where a caller can inspect or override it, rather than being one fixed decision baked into the API for every user.

### `title_status`

The title status can be:

| Status         | Meaning                                                                                              |
| -------------- | ---------------------------------------------------------------------------------------------------- |
| `verified`     | A sufficiently strong match was found in a supported academic index                                  |
| `not-verified` | No suitable academic record was found                                                                |
| `web-resource` | The citation appears to refer to a non-academic web resource and is not sent to the verification API |

For example, a blog post, product page, or other general web resource may be classified as `web-resource`. Such references are intentionally excluded from academic-index verification because they are not expected to appear in arXiv or Crossref.

### `matched_source`

When a citation is successfully matched, this indicates where the record was found:

```text
arxiv
crossref
none
```

`none` means that no supported source produced a usable match.

### `author_status`

When a title match exists, SafeRef can also compare the citation's authors with the authors associated with the matched record:

```text
exact
partial
mismatch
unknown
N/A
```

These values should be interpreted together with the title result rather than as independent proof of authenticity.

### Title-match flagging

Pure title-embedding similarity is a weak fake-title detector on its own — in testing, most fabricated titles still scored above the verification threshold on similarity alone. Requiring the matched title to be an **exact** match (after normalizing whitespace/punctuation/case) is a much stronger signal, but it also incorrectly flags a real minority of genuinely correct citations whose parsed title has minor OCR/formatting noise.

Because of that tradeoff, `title_exact_match`/`title_similarity` are always computed and returned, but do **not** contribute to `flagged` by default. `flagged`/`flag_reasons` are `True`/non-empty when:

* `title_status` is not `verified` (and not `web-resource`), or
* `author_status` is `mismatch`.

If you also want an exact-title mismatch to count as a flag reason, opt in explicitly:

```python
results = verify_pdf(
    "paper.pdf",
    api_url="https://api.example.com",
    flag_on_title_mismatch=True,
)
```

`title_similarity` is offered as extra context for judgment calls in the middle ground between "clearly correct" and "clearly fabricated" — it is not itself a pass/fail threshold; no similarity cutoff was found to reliably beat plain exact-match on the accuracy/false-flag tradeoff.

#### Seeing exactly what differs: `title_diff`

`title_exact_match` and `title_similarity` can both miss the same real case: a citation title with one letter changed into a different, real-looking word (e.g. "Aurar" for the real "Auror") still scores a high similarity ratio, and a boolean exact-match tells you *that* it differs, not *how*. `title_diff` gives you the actual character-level diff so you can judge that for yourself:

```python
from saferef_client.titles import title_diff

diff = title_diff(result["parsed_title"], result["matched_title"])
```

Call it when `title_exact_match` is `False` (it returns `None` if the titles already match, or if either is missing). It diffs the same normalized titles `title_exact_match` is based on, so punctuation/casing noise never shows up here. Each item is `{"tag", "parsed", "matched"}`, straight from `difflib.SequenceMatcher.get_opcodes()` — `"equal"`, `"replace"`, `"insert"` (present only in the matched title), or `"delete"` (present only in the parsed title):

```python
>>> title_diff(
...     "Aurar: defending against poisoning attacks in collaborative deep learning systems",
...     "Auror: defending against poisoning attacks in collaborative deep learning systems",
... )
[
    {"tag": "equal",   "parsed": "aur", "matched": "aur"},
    {"tag": "replace", "parsed": "a",   "matched": "o"},
    {"tag": "equal",   "parsed": "r: defending against poisoning attacks in collaborative deep learning systems",
                        "matched": "r: defending against poisoning attacks in collaborative deep learning systems"},
]
```

A single `replace` op on one letter is easy to recognize as a real, substantive change; a title differing only by, say, a hyphen vs. an en-dash would show up as an equally small but obviously-cosmetic diff instead.

---

## Verification is not a verdict

It is important not to interpret SafeRef as a binary "real vs. fake" detector.

For example:

```text
title_status = not-verified
```

does **not** necessarily mean:

```text
"This paper does not exist."
```

It means that SafeRef could not find a sufficiently suitable record in the sources it checks.

Possible explanations include:

* the citation was parsed incorrectly from the PDF;
* the title contains OCR or formatting errors;
* the citation uses a substantially different title;
* the publication is indexed under different metadata;
* the work is too new to appear in a particular index;
* the work is not covered by arXiv or Crossref;
* the citation refers to a legitimate but obscure publication.

Likewise, a successful match should be treated as evidence of a corresponding indexed record, not as proof that the citation is being used correctly or that every piece of metadata is accurate.

**Use SafeRef to identify citations worth checking, not to make unsupported claims about whether a paper is genuine.**

---

## Parse citations without verification

If you only want to inspect the references extracted from a PDF, you can use `extract_citations()` directly:

```python
from saferef_client import extract_citations

citations = extract_citations("paper.pdf")

for citation in citations:
    print(citation)
```

This performs the extraction step without sending the citations to a SafeRef API server.

This is useful when you want to:

* inspect parsing quality;
* filter citations locally;
* debug extraction;
* build your own verification workflow;
* review what information would be sent to the API.

---

## Verify titles without a PDF

You don't have to start with a PDF. If you already have a title (from a spreadsheet, a different parser, manual entry — anything), `verify_titles()` sends it straight to the SafeRef API without needing citation records:

```python
from saferef_client import verify_titles

# a single title, no author info
result = verify_titles(
    "Attention is all you need",
    api_url="https://api.example.com",
)

# a single title, with authors
result = verify_titles(
    "Attention is all you need",
    api_url="https://api.example.com",
    authors=["Ashish Vaswani"],
)

# a list of titles -- authors, when given, is one list per title (use [] for none)
results = verify_titles(
    ["Attention is all you need", "A paper with no known authors"],
    api_url="https://api.example.com",
    authors=[["Ashish Vaswani"], []],
)
```

Pass a single title and you get back a single result dict; pass a list and you get back a list, in the same order — same fields as `verify_pdf()`'s rows (`title_status`, `matched_source`, `matched_title`, `author_status`, `title_exact_match`, etc., see the [result fields table](#result-fields) above).

### Lower-level: `verify()`

If you already have full citation records — e.g. from `extract_citations()`, or your own extraction pipeline producing the same `{citation_id, parsed_title, parsed_authors}` shape — `verify()` sends those directly without `verify_titles()`'s title/author-list bookkeeping:

```python
from saferef_client import verify

results = verify(
    citations,
    api_url="https://api.example.com",
)
```

This lets you use SafeRef as a verification layer independently of its PDF extraction functionality.

---

## Author privacy

`author_status` is always computed **locally by the library**, regardless of `send_authors` — the server returns `db_authors` for every title match either way, and the same comparison logic runs on the caller's own machine either way. `send_authors` only controls whether the parsed author names are also sent to the server in the request body; it does not change any result.

By default, SafeRef sends the parsed author names together with each citation title:

```python
results = verify_pdf(
    "paper.pdf",
    api_url="https://api.example.com",
    send_authors=True,
)
```

If you do not want parsed author names to leave your machine at all, disable this:

```python
results = verify_pdf(
    "paper.pdf",
    api_url="https://api.example.com",
    send_authors=False,
)
```

Either way, the resulting `author_status` is identical — `send_authors` is purely a privacy knob, not an accuracy one.