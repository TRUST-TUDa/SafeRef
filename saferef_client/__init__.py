"""
saferef_client

Client library: extract citations from a PDF locally (no ML dependencies),
then ask a SafeRef API server whether each one verifies. See client.py's
docstring for the full contract.

    from saferef_client import verify_pdf
    results = verify_pdf("paper.pdf", api_url="https://api.example.com")
"""

from .authors import compare_authors
from .client import extract_citations, verify, verify_pdf, verify_titles
from .parsing import Parser
from .titles import compare_titles, title_diff

__all__ = ["extract_citations", "verify", "verify_pdf", "verify_titles", "Parser", "compare_authors", "compare_titles", "title_diff"]
