"""Tests for document section splitting."""

from exnot.parser.base import ExtractedDocument, ExtractedTable
from exnot.parser.section_splitter import (
    DocumentSection,
    classify_context_sections,
    group_sections,
    should_use_sectioned_extraction,
    split_document,
)


def _make_doc(text, tables=None, page_count=0):
    return ExtractedDocument(
        full_text=text,
        tables=tables or [],
        page_count=page_count,
        metadata={},
    )


def _make_table(title="", page_number=None, headers=None, rows=None):
    return ExtractedTable(
        headers=headers or ["Col1", "Col2"],
        rows=rows or [["a", "b"]],
        title=title,
        page_number=page_number,
        footnotes=[],
    )


# --- split_document (PDF) ---


def test_split_pdf_text_by_pages():
    """PDF page markers should produce sections when headings are found."""
    text = (
        "--- Page 1 ---\n"
        "TRANSACTION FEES\n"
        "Customer maker fee is $0.50\n"
        "--- Page 2 ---\n"
        "COMPLEX ORDER FEES\n"
        "Complex maker fee is $0.30\n"
    )
    table1 = _make_table("Fees", page_number=1)
    table2 = _make_table("Complex", page_number=2)
    doc = _make_doc(text, [table1, table2], page_count=2)

    sections = split_document(doc, format_hint="pdf")

    assert len(sections) >= 2
    assert any("TRANSACTION FEES" in s.heading for s in sections)
    assert any("COMPLEX ORDER FEES" in s.heading for s in sections)


def test_heading_detection_all_caps():
    """All-caps lines should be detected as headings."""
    text = (
        "--- Page 1 ---\n"
        "REGULAR OPTIONS TRANSACTION FEES\n"
        "Some fee data here $0.50\n"
        "--- Page 2 ---\n"
        "COMPLEX ORDER FEES AND REBATES\n"
        "More fee data $0.30\n"
    )
    doc = _make_doc(text, page_count=2)
    sections = split_document(doc, format_hint="pdf")

    headings = [s.heading for s in sections]
    assert "REGULAR OPTIONS TRANSACTION FEES" in headings
    assert "COMPLEX ORDER FEES AND REBATES" in headings


def test_heading_detection_numbered():
    """Numbered section headings should be detected."""
    text = "--- Page 1 ---\n1. Regular Orders\nFee data here\n--- Page 2 ---\n2. Complex Orders\nMore data\n"
    doc = _make_doc(text, page_count=2)
    sections = split_document(doc, format_hint="pdf")

    headings = [s.heading for s in sections]
    assert "1. Regular Orders" in headings
    assert "2. Complex Orders" in headings


def test_pages_without_headings_merge():
    """Pages without headings should be merged into the preceding section."""
    text = (
        "--- Page 1 ---\n"
        "TRANSACTION FEES\n"
        "Fee data page 1\n"
        "--- Page 2 ---\n"
        "Continued fee data page 2\n"
        "--- Page 3 ---\n"
        "INDEX OPTIONS FEES\n"
        "Index fee data\n"
    )
    doc = _make_doc(text, page_count=3)
    sections = split_document(doc, format_hint="pdf")

    # Page 2 has no heading, should merge with page 1's section
    assert len(sections) == 2
    tx_section = [s for s in sections if "TRANSACTION FEES" in s.heading][0]
    assert "page 2" in tx_section.text


def test_tables_assigned_by_page():
    """Tables should be assigned to the correct section by page_number."""
    text = "--- Page 1 ---\nREGULAR FEES\nSome text\n--- Page 3 ---\nCOMPLEX FEES\nOther text\n"
    t1 = _make_table("Reg Table", page_number=1)
    t2 = _make_table("Complex Table", page_number=3)
    doc = _make_doc(text, [t1, t2], page_count=3)

    sections = split_document(doc, format_hint="pdf")
    reg = [s for s in sections if "REGULAR" in s.heading][0]
    cpx = [s for s in sections if "COMPLEX" in s.heading][0]

    assert t1 in reg.tables
    assert t2 in cpx.tables


# --- classify_context_sections ---


def test_context_classification_keywords():
    """Sections with context keywords should be marked as context."""
    sections = [
        DocumentSection(heading="Definitions", text="Market Maker means..."),
        DocumentSection(heading="Appendix A", text="See glossary for terms"),
        DocumentSection(heading="Transaction Fees", text="Customer maker $0.50"),
    ]
    result = classify_context_sections(sections)

    assert result[0].is_context is True
    assert result[1].is_context is True
    assert result[2].is_context is False


def test_context_classification_footnotes():
    """Sections with footnote keywords should be context."""
    sections = [
        DocumentSection(
            heading="Footnotes and Endnotes",
            text="1. See regulatory filing for details.",
        ),
        DocumentSection(
            heading="Fee Table",
            text="Customer: $0.50 per contract",
            tables=[_make_table("Fees")],
        ),
    ]
    result = classify_context_sections(sections)

    assert result[0].is_context is True
    assert result[1].is_context is False


def test_fee_section_not_marked_context():
    """Fee sections with dollar amounts should NOT be marked as context."""
    sections = [
        DocumentSection(
            heading="TRANSACTION FEES",
            text="Customer Maker $0.50\nCustomer Taker $0.45\nProfessional $0.85",
            tables=[_make_table("Fees", rows=[["Customer", "$0.50", "$0.45"]])],
        ),
    ]
    result = classify_context_sections(sections)
    assert result[0].is_context is False


# --- group_sections ---


def test_group_sections_respects_budget():
    """Groups should stay under the character budget."""
    sections = [DocumentSection(heading=f"Section {i}", text="x" * 5000) for i in range(5)]
    groups = group_sections(sections, char_budget=12000)

    # 5 sections of 5K chars each, budget 12K → at least 3 groups
    assert len(groups) >= 3
    for g in groups:
        # Each group should have at most 2 sections (2*5K = 10K < 12K)
        assert len(g.sections) <= 2


def test_group_sections_single_large():
    """A single section over budget should get its own group."""
    sections = [
        DocumentSection(heading="Big", text="x" * 20000),
        DocumentSection(heading="Small", text="x" * 3000),
    ]
    groups = group_sections(sections, char_budget=15000)

    assert len(groups) == 2
    assert groups[0].sections[0].heading == "Big"
    assert groups[1].sections[0].heading == "Small"


# --- should_use_sectioned_extraction ---


def test_should_use_sectioned_large_doc():
    """Documents over 20K chars should use sectioned extraction."""
    doc = _make_doc("x" * 25000)
    assert should_use_sectioned_extraction(doc) is True


def test_should_use_sectioned_small_doc():
    """Small documents should NOT use sectioned extraction."""
    doc = _make_doc("x" * 5000)
    assert should_use_sectioned_extraction(doc) is False


def test_should_use_sectioned_many_tables():
    """Documents with >8 tables should use sectioned extraction."""
    tables = [_make_table(f"Table {i}") for i in range(10)]
    doc = _make_doc("short text", tables)
    assert should_use_sectioned_extraction(doc) is True


# --- split_document (CSV) ---


def test_split_csv_sections():
    """CSV section markers should produce sections."""
    text = (
        "--- Section 1: Transaction Fees ---\n"
        "Type | Maker | Taker\n"
        "Customer | $0.50 | $0.45\n"
        "\n"
        "--- Section 2: Complex Orders ---\n"
        "Type | Fee\n"
        "Customer | $0.30\n"
    )
    t1 = _make_table("Transaction Fees")
    t2 = _make_table("Complex Orders")
    doc = _make_doc(text, [t1, t2])

    sections = split_document(doc, format_hint="csv")
    assert len(sections) == 2
    assert "Transaction Fees" in sections[0].heading
    assert "Complex Orders" in sections[1].heading
