"""Tests for the Docling PDF parser.

These tests require docling to be installed and are skipped otherwise.
"""

import pytest

_docling_available = True
try:
    import docling  # noqa: F401
except ImportError:
    _docling_available = False

pytestmark = pytest.mark.skipif(not _docling_available, reason="docling not installed")


def test_extract_returns_extracted_document():
    """DoclingPdfParser.extract() should return a well-formed ExtractedDocument."""
    from exnot.parser.base import ExtractedDocument
    from exnot.parser.docling_parser import DoclingPdfParser

    # Minimal valid PDF (single page, no content)
    import fitz

    doc = fitz.open()
    page = doc.new_page()
    page.insert_text((72, 72), "TRANSACTION FEES\nCustomer $0.50")
    pdf_bytes = doc.tobytes()
    doc.close()

    parser = DoclingPdfParser()
    result = parser.extract(pdf_bytes)

    assert isinstance(result, ExtractedDocument)
    assert result.full_text
    assert result.page_count >= 1
    assert result.metadata["parser"] == "docling"
    assert "markdown" in result.metadata
    assert result.metadata["markdown"]


def test_page_markers_present():
    """Page-marked text should contain --- Page N --- markers."""
    from exnot.parser.docling_parser import DoclingPdfParser

    import fitz

    doc = fitz.open()
    for i in range(2):
        page = doc.new_page()
        page.insert_text((72, 72), f"Page {i + 1} content")
    pdf_bytes = doc.tobytes()
    doc.close()

    parser = DoclingPdfParser()
    result = parser.extract(pdf_bytes)

    assert "--- Page 1 ---" in result.full_text


def test_singleton_converter():
    """Multiple DoclingPdfParser instances should share the same converter."""
    from exnot.parser.docling_parser import DoclingPdfParser

    p1 = DoclingPdfParser()
    p2 = DoclingPdfParser()
    assert p1._converter is p2._converter
