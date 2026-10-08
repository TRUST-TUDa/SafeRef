# SafeRef

**Extract academic citations from PDFs and verify them against scholarly indexes.**

SafeRef is a lightweight Python client that extracts references from academic PDFs and checks them against scholarly records through the SafeRef API.

PDF parsing, citation extraction, and author comparison are performed locally. The SafeRef API matches citation titles and authors against indexed records.

> **SafeRef is a verification aid, not a truth detector.**
>
> A `not-verified` result does **not** mean a paper is hallucinated or nonexistent. The citation may have been parsed incorrectly, differ from the indexed version, or simply not be present in the available scholarly indexes. Use SafeRef results as signals for further investigation, not definitive judgments.

---

## Installation

Clone the repository and install the library's dependencies:

```bash
git clone https://github.com/TRUST-TUDa/SafeRef.git
cd SafeRef

pip install -r requirements.txt
```

SafeRef has deliberately minimal client-side dependencies. The library only needs the components required for:

* PDF parsing
* citation extraction
* HTTP communication with the SafeRef API

---

## Quick start

Verifying a PDF takes only a few lines. By default, requests go to the project's own public API instance.
Pass your own `api_url` if you're running a different server:

```python
from saferef_client import verify_pdf, title_diff

results = verify_pdf("path/to/document.pdf")
# or, against your own server:
# results = verify_pdf("path/to/document.pdf", api_url="https://your-server.example.com")

for result in results:
    print(
        result["citation_id"],
        result["title_status"],
        result["author_status"],
        result["raw_citation"],
    )
    if result["title_exact_match"] is False:
        print("title diff:", title_diff(result["parsed_title"], result["matched_title"]))
```

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
| `raw_citation`      | The citation text exactly as it appeared in the PDF, before parsing       |
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


### `title_status`

The title status can be:

| Status         | Meaning                                                                                              |
| -------------- | ---------------------------------------------------------------------------------------------------- |
| `verified`     | A sufficiently strong match was found in a supported academic index                                  |
| `not-verified` | No suitable academic record was found                                                                |
| `web-resource` | The citation appears to refer to a non-academic web resource and is not sent to the verification API |

For example, a blog post, product page, or other general web resource may be classified as `web-resource`. Such references are intentionally excluded from academic-index verification because they are not expected to appear in our academic dataset.

---

## Verify titles without a PDF

Use `verify_titles()` to verify titles directly, without extracting them from a PDF.

```python
from saferef_client import verify_titles

# Single title
result = verify_titles("Attention is all you need")

# Title with authors
result = verify_titles(
    "Attention is all you need",
    authors=["Ashish Vaswani"],
)

# Multiple titles
results = verify_titles(
    ["Attention is all you need", "Deep Residual Learning for Image Recognition"],
    authors=[["Ashish Vaswani"], []],
)
```

Pass a single title and you get back a single result dict; pass a list and you get back a list, in the same order with same fields as `verify_pdf()`'s rows (`title_status`, `matched_source`, `matched_title`, `author_status`, `title_exact_match`, etc., see the [result fields table](#result-fields) above).

---

## Parse citations without verification

If you only want to inspect the references extracted from a PDF, you can use `extract_citations()` directly:

```python
from saferef_client import extract_citations

citations = extract_citations("path/to/document.pdf")

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

### Lower-level: `verify()`

If you already have full citation records, e.g. from `extract_citations()`, or your own extraction pipeline, using the same `{citation_id, parsed_title, parsed_authors}` format, use `verify()` to analyze those directly without `verify_titles()`'s title/author-list bookkeeping:

```python
from saferef_client import verify

results = verify(citations)
```

This lets you use SafeRef as a verification layer independently of its PDF extraction functionality.

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

The API compares citations against supported scholarly sources, currently:

* **arXiv**
* **Crossref**
* **DBLP**

Non-academic web resources such as blog posts and product pages are identified separately and are not sent to the academic verification API.