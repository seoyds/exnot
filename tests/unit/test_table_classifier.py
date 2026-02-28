"""Tests for table classification (fee vs non-fee)."""
from exnot.parser.base import ExtractedTable
from exnot.parser.table_classifier import classify_table, classify_tables


def _make_table(headers, rows=None, title=""):
    return ExtractedTable(
        headers=headers,
        rows=rows or [["$0.50", "$0.25"]],
        title=title,
        page_number=1,
        footnotes=[],
    )


def test_fee_table_detected_by_headers():
    table = _make_table(["Account Type", "Maker", "Taker"])
    result = classify_table(table)
    assert result.is_fee_table is True


def test_fee_table_detected_by_dollar_values():
    table = _make_table(["Type", "Rate"], rows=[["Customer", "$0.50"]])
    result = classify_table(table)
    assert result.is_fee_table is True


def test_fee_table_detected_by_rebate_header():
    table = _make_table(["Tier", "Per Contract Rebate"])
    result = classify_table(table)
    assert result.is_fee_table is True


def test_non_fee_table_connectivity():
    table = _make_table(
        ["Connection Type", "Monthly Fees"],
        rows=[["10Gb Connection", "$5,000 per month"]],
    )
    result = classify_table(table)
    assert result.is_fee_table is False


def test_non_fee_table_port_fees():
    table = _make_table(
        ["FIX Ports", "BOX Monthly Port Fees"],
        rows=[["1st FIX Port", "$540 per port per month"]],
    )
    result = classify_table(table)
    assert result.is_fee_table is False


def test_non_fee_table_membership():
    table = _make_table(
        ["Monthly BOX Market\nMaker Trading Permit Fee", "Per Class"],
        rows=[["$4,000", "Up to and including 10 Classes"]],
    )
    result = classify_table(table)
    assert result.is_fee_table is False


def test_title_page_table_excluded():
    table = _make_table(
        ["", "", ""],
        rows=[["", "", "As of February 2, 2026\nFee Schedule"]],
    )
    result = classify_table(table)
    assert result.is_fee_table is False


def test_classify_tables_returns_both():
    fee_table = _make_table(["Account Type", "Maker", "Taker"])
    port_table = _make_table(
        ["FIX Ports", "Monthly Fees"],
        rows=[["Port 1", "$540/month"]],
    )
    results = classify_tables([fee_table, port_table])
    assert len(results) == 2
    assert results[0].is_fee_table is True
    assert results[1].is_fee_table is False
