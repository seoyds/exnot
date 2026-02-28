"""Tests for rules-based profile extraction."""
from exnot.parser.base import ExtractedTable
from exnot.profiles.extractor import extract_from_mapping, parse_amount


def test_parse_amount_positive():
    assert parse_amount("$0.50") == 0.50


def test_parse_amount_negative_parens():
    assert parse_amount("($0.20)") == -0.20


def test_parse_amount_negative_sign():
    assert parse_amount("-$0.05") == -0.05


def test_parse_amount_zero():
    assert parse_amount("$0.00") == 0.00


def test_parse_amount_no_dollar_sign():
    assert parse_amount("0.50") == 0.50


def test_parse_amount_empty():
    assert parse_amount("") is None


def test_parse_amount_text():
    assert parse_amount("N/A") is None


def test_extract_simple_grid():
    """Extract from a typical maker/taker grid table."""
    table = ExtractedTable(
        headers=["Account Type", "Contra Party", "Maker", "Taker"],
        rows=[
            ["Public Customer", "Non-Customer", "$0.00", "($0.20)"],
            ["Professional", "Non-Customer", "$0.50", "$0.45"],
            ["Market Maker", "Non-Customer", "$0.25", "$0.30"],
        ],
        title="Transaction Fees",
        page_number=3,
        footnotes=[],
    )
    mapping = {
        "table_index": 0,
        "is_fee_table": True,
        "layout": "GRID",
        "row_axis_col": 0,
        "has_contra_party_column": True,
        "contra_party_col_index": 1,
        "column_groups": [
            {
                "label": "Penny",
                "security_class": "PENNY",
                "columns": [
                    {"header": "Maker", "fee_type": "MAKER", "col_index": 2},
                    {"header": "Taker", "fee_type": "TAKER", "col_index": 3},
                ],
            }
        ],
        "row_mappings": {
            "Public Customer": {"participant_type": "CUSTOMER"},
            "Professional": {"participant_type": "PROFESSIONAL"},
            "Market Maker": {"participant_type": "MARKET_MAKER"},
        },
        "section_ref": "Section IV.A",
        "order_type": "SIMPLE",
    }

    fees = extract_from_mapping(table, mapping)
    assert len(fees) == 6  # 3 rows x 2 columns

    # Check first fee: Customer Maker
    cust_maker = [f for f in fees if f["participant_type"] == "CUSTOMER" and f["fee_type"] == "MAKER"][0]
    assert cust_maker["amount"] == 0.00
    assert cust_maker["is_rebate"] is False
    assert cust_maker["security_class"] == "PENNY"
    assert cust_maker["contra_party_type"] == "NON_CUSTOMER"
    assert cust_maker["section_ref"] == "Section IV.A"
    assert cust_maker["order_type"] == "SIMPLE"

    # Check Customer Taker (rebate)
    cust_taker = [f for f in fees if f["participant_type"] == "CUSTOMER" and f["fee_type"] == "TAKER"][0]
    assert cust_taker["amount"] == -0.20
    assert cust_taker["is_rebate"] is True


def test_extract_multi_security_class():
    """Table with Penny + Non-Penny column groups."""
    table = ExtractedTable(
        headers=["Account Type", "Penny Maker", "Penny Taker", "Non-Penny Maker", "Non-Penny Taker"],
        rows=[["Public Customer", "$0.00", "($0.15)", "$0.00", "($0.50)"]],
        title="",
        page_number=1,
        footnotes=[],
    )
    mapping = {
        "table_index": 0,
        "is_fee_table": True,
        "layout": "GRID",
        "row_axis_col": 0,
        "has_contra_party_column": False,
        "column_groups": [
            {
                "label": "Penny",
                "security_class": "PENNY",
                "columns": [
                    {"header": "Penny Maker", "fee_type": "MAKER", "col_index": 1},
                    {"header": "Penny Taker", "fee_type": "TAKER", "col_index": 2},
                ],
            },
            {
                "label": "Non-Penny",
                "security_class": "NON_PENNY",
                "columns": [
                    {"header": "Non-Penny Maker", "fee_type": "MAKER", "col_index": 3},
                    {"header": "Non-Penny Taker", "fee_type": "TAKER", "col_index": 4},
                ],
            },
        ],
        "row_mappings": {
            "Public Customer": {"participant_type": "CUSTOMER"},
        },
        "section_ref": "Section IV",
        "order_type": "SIMPLE",
    }

    fees = extract_from_mapping(table, mapping)
    assert len(fees) == 4  # 1 row x 4 columns (2 security classes x 2 fee types)

    np_taker = [f for f in fees if f["security_class"] == "NON_PENNY" and f["fee_type"] == "TAKER"][0]
    assert np_taker["amount"] == -0.50
    assert np_taker["is_rebate"] is True


def test_extract_skips_unknown_rows():
    """Rows not in row_mappings are skipped."""
    table = ExtractedTable(
        headers=["Type", "Fee"],
        rows=[
            ["Public Customer", "$0.50"],
            ["UNKNOWN ROW", "$9.99"],
        ],
        title="",
        page_number=1,
        footnotes=[],
    )
    mapping = {
        "table_index": 0,
        "is_fee_table": True,
        "layout": "GRID",
        "row_axis_col": 0,
        "has_contra_party_column": False,
        "column_groups": [
            {
                "label": "All",
                "security_class": "ALL",
                "columns": [{"header": "Fee", "fee_type": "TRANSACTION", "col_index": 1}],
            }
        ],
        "row_mappings": {"Public Customer": {"participant_type": "CUSTOMER"}},
        "section_ref": "",
        "order_type": "SIMPLE",
    }

    fees = extract_from_mapping(table, mapping)
    assert len(fees) == 1
    assert fees[0]["participant_type"] == "CUSTOMER"
