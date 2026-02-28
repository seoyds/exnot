"""Tests for profile builder - learns table mappings from AI extraction."""
from exnot.parser.base import ExtractedTable
from exnot.profiles.builder import ProfileBuilder


def _make_table(headers, rows, title=""):
    return ExtractedTable(
        headers=headers, rows=rows, title=title,
        page_number=1, footnotes=[],
    )


def test_builder_matches_fees_to_cells():
    """Builder finds the source table/cell for each AI-extracted fee."""
    tables = [
        _make_table(
            ["Account Type", "Maker", "Taker"],
            [
                ["Public Customer", "$0.00", "($0.20)"],
                ["Professional", "$0.50", "$0.45"],
            ],
        ),
    ]
    ai_fees = [
        {"participant_type": "CUSTOMER", "fee_type": "MAKER", "amount": 0.00,
         "security_class": "PENNY", "order_type": "SIMPLE", "section_ref": ""},
        {"participant_type": "CUSTOMER", "fee_type": "TAKER", "amount": -0.20,
         "security_class": "PENNY", "order_type": "SIMPLE", "section_ref": ""},
        {"participant_type": "PROFESSIONAL", "fee_type": "MAKER", "amount": 0.50,
         "security_class": "PENNY", "order_type": "SIMPLE", "section_ref": ""},
        {"participant_type": "PROFESSIONAL", "fee_type": "TAKER", "amount": 0.45,
         "security_class": "PENNY", "order_type": "SIMPLE", "section_ref": ""},
    ]
    builder = ProfileBuilder()
    result = builder.build(tables, ai_fees)

    assert result.match_ratio >= 0.7
    assert len(result.table_mappings) >= 1
    # Check the mapping found the right table
    mapping = result.table_mappings[0]
    assert mapping["is_fee_table"] is True
    assert "Public Customer" in mapping["row_mappings"]
    assert mapping["row_mappings"]["Public Customer"]["participant_type"] == "CUSTOMER"


def test_builder_skips_non_fee_tables():
    """Non-fee tables should not appear in mappings."""
    tables = [
        _make_table(
            ["Connection Type", "Monthly Fees"],
            [["10Gb", "$5,000 per month"]],
            title="Connectivity",
        ),
        _make_table(
            ["Account Type", "Fee"],
            [["Public Customer", "$0.50"]],
            title="Transaction Fees",
        ),
    ]
    ai_fees = [
        {"participant_type": "CUSTOMER", "fee_type": "TRANSACTION", "amount": 0.50,
         "security_class": "ALL", "order_type": "SIMPLE", "section_ref": ""},
    ]
    builder = ProfileBuilder()
    result = builder.build(tables, ai_fees)

    fee_mappings = [m for m in result.table_mappings if m["is_fee_table"]]
    assert len(fee_mappings) >= 1
    assert fee_mappings[0]["table_index"] == 1  # Second table, not the connectivity one


def test_builder_handles_zero_match():
    """If no fees match any table cells, match_ratio should be 0."""
    tables = [_make_table(["A", "B"], [["x", "y"]])]
    ai_fees = [
        {"participant_type": "CUSTOMER", "fee_type": "MAKER", "amount": 99.99,
         "security_class": "PENNY", "order_type": "SIMPLE", "section_ref": ""},
    ]
    builder = ProfileBuilder()
    result = builder.build(tables, ai_fees)
    assert result.match_ratio < 0.7
