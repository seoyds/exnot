"""Tests for table pre-filtering in the extraction pipeline.

The table filtering behavior (excluding non-fee tables like connectivity/ports)
is now handled by the table classifier (rule-based), which is called from the
orchestrator's extract_section tool.
"""

from exnot.parser.base import ExtractedTable
from exnot.parser.table_classifier import classify_tables


def test_classify_tables_filters_non_fee_tables():
    """Non-fee tables (ports, connectivity) should be classified as non-fee."""
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

    results = classify_tables([fee_table, port_table])

    assert results[0].is_fee_table is True, f"Fee table should be classified as fee: {results[0].reason}"
    assert results[1].is_fee_table is False, f"Port table should be classified as non-fee: {results[1].reason}"
