"""Tests for table fingerprinting."""

from exnot.parser.base import ExtractedTable
from exnot.profiles.fingerprint import (
    compare_fingerprints,
    fingerprint_all_tables,
    fingerprint_table,
)


def _make_table(headers, rows=None):
    return ExtractedTable(
        headers=headers,
        rows=rows or [],
        title="",
        page_number=1,
        footnotes=[],
    )


def test_fingerprint_is_stable():
    t1 = _make_table(["Account Type", "Maker", "Taker"])
    t2 = _make_table(["Account Type", "Maker", "Taker"])
    assert fingerprint_table(t1) == fingerprint_table(t2)


def test_fingerprint_ignores_footnote_refs():
    """Footnote numbers like '20F21' should not affect fingerprint."""
    t1 = _make_table(["PIP Orders20F21", "Break-Up Credit"])
    t2 = _make_table(["PIP Orders", "Break-Up Credit"])
    assert fingerprint_table(t1) == fingerprint_table(t2)


def test_fingerprint_ignores_case():
    t1 = _make_table(["Account Type", "MAKER"])
    t2 = _make_table(["account type", "maker"])
    assert fingerprint_table(t1) == fingerprint_table(t2)


def test_fingerprint_ignores_extra_whitespace():
    t1 = _make_table(["Account  Type", " Maker "])
    t2 = _make_table(["Account Type", "Maker"])
    assert fingerprint_table(t1) == fingerprint_table(t2)


def test_different_headers_different_fingerprint():
    t1 = _make_table(["Account Type", "Maker", "Taker"])
    t2 = _make_table(["Tier", "Volume", "Rebate"])
    assert fingerprint_table(t1) != fingerprint_table(t2)


def test_fingerprint_all_tables():
    tables = [
        _make_table(["A", "B"]),
        _make_table(["C", "D"]),
    ]
    fps = fingerprint_all_tables(tables)
    assert len(fps) == 2
    assert all(isinstance(fp, str) for fp in fps.keys())


def test_compare_fingerprints_all_match():
    stored = {"fp1": {"table_index": 0}, "fp2": {"table_index": 1}}
    current = {"fp1": 0, "fp2": 1}
    result = compare_fingerprints(stored, current)
    assert result.all_match is True
    assert result.changed_indices == []
    assert result.new_indices == []


def test_compare_fingerprints_one_changed():
    stored = {"fp1": {"table_index": 0}, "fp2": {"table_index": 1}}
    current = {"fp1": 0, "fp_new": 1}  # fp2 replaced by fp_new
    result = compare_fingerprints(stored, current)
    assert result.all_match is False
    assert 1 in result.changed_indices


def test_compare_fingerprints_new_table_added():
    stored = {"fp1": {"table_index": 0}}
    current = {"fp1": 0, "fp2": 1}
    result = compare_fingerprints(stored, current)
    assert result.all_match is False
    assert 1 in result.new_indices
