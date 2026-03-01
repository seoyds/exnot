"""Tests for the PDF parser factory."""

from unittest.mock import MagicMock, patch

from exnot.parser.factory import get_pdf_parser
from exnot.parser.pdf_parser import PdfParser


def test_default_returns_pymupdf():
    """Default config should return PdfParser."""
    mock_settings = MagicMock()
    mock_settings.pdf_parser_backend = "pymupdf"
    with patch("exnot.config.get_settings", return_value=mock_settings):
        parser = get_pdf_parser()
    assert isinstance(parser, PdfParser)


def test_unknown_backend_returns_pymupdf():
    """Unknown backend value should fall back to PdfParser."""
    mock_settings = MagicMock()
    mock_settings.pdf_parser_backend = "unknown"
    with patch("exnot.config.get_settings", return_value=mock_settings):
        parser = get_pdf_parser()
    assert isinstance(parser, PdfParser)


def test_docling_import_error_falls_back(caplog):
    """If docling is not installed, factory should fall back to PdfParser."""
    mock_settings = MagicMock()
    mock_settings.pdf_parser_backend = "docling"

    original_import = __builtins__.__import__ if hasattr(__builtins__, "__import__") else __import__

    def mock_import(name, *args, **kwargs):
        if "docling_parser" in name or (
            "exnot.parser.docling_parser" in name
        ):
            raise ImportError("No module named 'docling'")
        return original_import(name, *args, **kwargs)

    with (
        patch("exnot.config.get_settings", return_value=mock_settings),
        patch("builtins.__import__", side_effect=mock_import),
    ):
        parser = get_pdf_parser()

    assert isinstance(parser, PdfParser)


def test_docling_section_splitter_format_hint():
    """Section splitter should accept 'docling' as format_hint."""
    from exnot.parser.base import ExtractedDocument
    from exnot.parser.section_splitter import split_document

    doc = ExtractedDocument(
        full_text="Some text",
        tables=[],
        page_count=1,
        metadata={
            "parser": "docling",
            "markdown": "## Transaction Fees\n\nCustomer $0.50\n\n## Complex Orders\n\nCustomer $0.30\n",
        },
    )
    sections = split_document(doc, format_hint="docling")

    assert len(sections) == 2
    assert sections[0].heading == "Transaction Fees"
    assert sections[1].heading == "Complex Orders"


def test_docling_markdown_no_headings_falls_back():
    """Docling markdown without headings should fall back to PDF splitting."""
    from exnot.parser.base import ExtractedDocument
    from exnot.parser.section_splitter import split_document

    doc = ExtractedDocument(
        full_text="--- Page 1 ---\nSOME HEADING\nSome text",
        tables=[],
        page_count=1,
        metadata={
            "parser": "docling",
            "markdown": "Just plain text without any headings at all.",
        },
    )
    sections = split_document(doc, format_hint="docling")
    # Falls back to PDF splitter since no markdown headings found
    assert len(sections) >= 1


def test_ai_extractor_orchestrator_prompt_mentions_format():
    """AI extractor orchestrator prompt should reflect document format."""
    from exnot.parser.ai_extractor import AIExtractor
    from exnot.parser.base import ExtractedDocument

    doc = ExtractedDocument(
        full_text="--- Page 1 ---\nSome text",
        tables=[],
        page_count=1,
        metadata={
            "parser": "docling",
            "markdown": "## Fees\n\n| Type | Amount |\n|------|--------|\n| Customer | $0.50 |\n",
        },
    )
    extractor = AIExtractor()
    prompt = extractor._build_orchestrator_prompt(doc, "TEST_EX")

    assert "Docling markdown" in prompt
    assert "TEST_EX" in prompt


def test_ai_extractor_orchestrator_prompt_includes_table_count():
    """AI extractor orchestrator prompt should include table count."""
    from exnot.parser.ai_extractor import AIExtractor
    from exnot.parser.base import ExtractedDocument, ExtractedTable

    doc = ExtractedDocument(
        full_text="Some fee text",
        tables=[
            ExtractedTable(
                headers=["Type", "Amount"],
                rows=[["Customer", "$0.50"]],
                title="Fees",
            )
        ],
        page_count=1,
        metadata={"parser": "pdf"},
    )
    extractor = AIExtractor()
    prompt = extractor._build_orchestrator_prompt(doc, "TEST_EX")

    assert "Tables: 1" in prompt
    assert "TEST_EX" in prompt
