"""Tests for AI extractor pre-filtering."""
from exnot.parser.base import ExtractedDocument, ExtractedTable
from exnot.parser.ai_extractor import AIExtractor


def _make_doc(tables):
    return ExtractedDocument(
        full_text="Sample fee schedule text",
        tables=tables,
        page_count=1,
        metadata={},
    )


def test_build_document_context_filters_non_fee_tables():
    """Non-fee tables (ports, connectivity) should be excluded from AI context."""
    fee_table = ExtractedTable(
        headers=["Account Type", "Maker", "Taker"],
        rows=[["Customer", "$0.50", "$0.45"]],
        title="Transaction Fees",
        page_number=1,
        footnotes=[],
    )
    port_table = ExtractedTable(
        headers=["FIX Ports", "BOX Monthly Port Fees"],
        rows=[["1st FIX Port", "$540 per port per month"]],
        title="Port Fees",
        page_number=2,
        footnotes=[],
    )
    doc = _make_doc([fee_table, port_table])

    extractor = AIExtractor.__new__(AIExtractor)  # Skip __init__ (no API key needed)
    context = extractor._build_document_context(doc)

    assert "Transaction Fees" in context or "Maker" in context
    assert "FIX Ports" not in context
    assert "$540 per port" not in context
