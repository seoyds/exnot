# Smart Extraction Pipeline Implementation Plan

> **For Claude:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task.

**Goal:** Replace AI-every-run fee extraction with a profile-based system where the first run learns table structure via AI and subsequent runs extract fees via rules-based column mappings — zero AI cost for ~95% of weekly runs.

**Architecture:** PDF/HTML tables are fingerprinted by their header structure. On first run, AI extracts fees and a ProfileBuilder reverse-engineers which table cell each fee came from, storing column→schema mappings as JSONB. On subsequent runs, if fingerprints match, a ProfileExtractor reads fees directly from table cells using stored mappings. Changed tables trigger targeted AI re-extraction.

**Tech Stack:** Python 3.12, SQLAlchemy 2.x (async), Alembic, pytest, Pydantic

**Design doc:** `docs/plans/2026-02-27-smart-extraction-pipeline-design.md`

---

## Task 1: ExchangeProfile Database Model

**Files:**
- Modify: `src/exnot/db/models.py`
- Create: `tests/unit/test_profile_model.py`

**Step 1: Write the failing test**

```python
# tests/unit/test_profile_model.py
"""Tests for ExchangeProfile model."""
import uuid
from datetime import datetime

from exnot.db.models import ExchangeProfile, ProfileStatus


def test_profile_status_enum():
    assert ProfileStatus.LEARNING.value == "LEARNING"
    assert ProfileStatus.ACTIVE.value == "ACTIVE"
    assert ProfileStatus.NEEDS_UPDATE.value == "NEEDS_UPDATE"


def test_exchange_profile_creation():
    profile = ExchangeProfile(
        exchange_id=uuid.uuid4(),
        profile_version=1,
        table_mappings=[],
        table_fingerprints={},
        section_metadata={},
        extraction_stats={},
        status=ProfileStatus.LEARNING,
    )
    assert profile.profile_version == 1
    assert profile.status == ProfileStatus.LEARNING
    assert profile.table_mappings == []
```

**Step 2: Run test to verify it fails**

Run: `pytest tests/unit/test_profile_model.py -v`
Expected: FAIL with `ImportError: cannot import name 'ExchangeProfile'`

**Step 3: Write minimal implementation**

Add to `src/exnot/db/models.py` after the existing enums:

```python
class ProfileStatus(str, enum.Enum):
    LEARNING = "LEARNING"
    ACTIVE = "ACTIVE"
    NEEDS_UPDATE = "NEEDS_UPDATE"
```

Add the model class after the existing models:

```python
class ExchangeProfile(Base):
    __tablename__ = "exchange_profiles"

    id: Mapped[uuid.UUID] = mapped_column(
        pg.UUID(as_uuid=True), primary_key=True, default=uuid.uuid4
    )
    exchange_id: Mapped[uuid.UUID] = mapped_column(
        pg.UUID(as_uuid=True), ForeignKey("exchanges.id"), unique=True, nullable=False
    )
    profile_version: Mapped[int] = mapped_column(default=1)
    table_mappings: Mapped[list] = mapped_column(pg.JSONB, default=list)
    table_fingerprints: Mapped[dict] = mapped_column(pg.JSONB, default=dict)
    section_metadata: Mapped[dict] = mapped_column(pg.JSONB, default=dict)
    extraction_stats: Mapped[dict] = mapped_column(pg.JSONB, default=dict)
    status: Mapped[ProfileStatus] = mapped_column(
        SAEnum(ProfileStatus, name="profilestatus", create_constraint=False),
        default=ProfileStatus.LEARNING,
    )
    created_at: Mapped[datetime] = mapped_column(DateTime, default=func.now())
    updated_at: Mapped[datetime] = mapped_column(
        DateTime, default=func.now(), onupdate=func.now()
    )

    exchange: Mapped["Exchange"] = relationship(back_populates="profile")
```

Also add to the `Exchange` model a backref:

```python
profile: Mapped["ExchangeProfile | None"] = relationship(
    back_populates="exchange", uselist=False
)
```

Note: Import `SAEnum` as `from sqlalchemy import Enum as SAEnum` at the top of models.py if not already imported. Check existing enum pattern used for `DiscoveryStatus`, `SnapshotStatus` etc and follow that same pattern.

**Step 4: Run test to verify it passes**

Run: `pytest tests/unit/test_profile_model.py -v`
Expected: PASS (2 tests)

**Step 5: Commit**

```bash
git add src/exnot/db/models.py tests/unit/test_profile_model.py
git commit -m "feat: add ExchangeProfile model and ProfileStatus enum"
```

---

## Task 2: Alembic Migration for exchange_profiles

**Files:**
- Create: Alembic migration (auto-generated)

**Step 1: Generate migration**

```bash
docker compose exec web alembic revision --autogenerate -m "add exchange_profiles table"
```

**Step 2: Review the generated migration**

Verify it creates:
- `exchange_profiles` table with all columns
- `profilestatus` enum type
- Unique constraint on `exchange_id`
- Foreign key to `exchanges.id`

**Step 3: Run migration**

```bash
docker compose exec web alembic upgrade head
```

**Step 4: Verify table exists**

```bash
docker compose exec db psql -U exnot -d exnot -c "\d exchange_profiles"
```

Expected: Table with id, exchange_id, profile_version, table_mappings, table_fingerprints, section_metadata, extraction_stats, status, created_at, updated_at

**Step 5: Commit**

```bash
git add alembic/versions/
git commit -m "feat: add exchange_profiles migration"
```

---

## Task 3: Table Classifier

Classifies parsed tables as fee-relevant or non-fee (connectivity, membership, market data).

**Files:**
- Create: `src/exnot/parser/table_classifier.py`
- Create: `tests/unit/test_table_classifier.py`

**Step 1: Write the failing tests**

```python
# tests/unit/test_table_classifier.py
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
```

**Step 2: Run tests to verify they fail**

Run: `pytest tests/unit/test_table_classifier.py -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'exnot.parser.table_classifier'`

**Step 3: Write minimal implementation**

```python
# src/exnot/parser/table_classifier.py
"""Classify parsed tables as fee-relevant or non-fee."""
import re
from dataclasses import dataclass

from exnot.parser.base import ExtractedTable

# Headers that indicate per-contract fee tables
FEE_INDICATORS = [
    "maker", "taker", "rebate", "per contract", "fee per",
    "customer", "professional", "market maker", "broker",
    "penny", "non-penny", "account type", "contra",
]

# Headers that indicate non-fee tables (connectivity, membership, etc.)
NON_FEE_INDICATORS = [
    "port", "connection", "subscription", "permit",
    "membership", "market data", "monthly fee", "per month",
    "per port", "report", "card submission",
]

# Dollar amounts in cells: $0.50, ($0.20), -$0.05
DOLLAR_PATTERN = re.compile(r"^[\s]*[\-]?\$?\(?\d+\.\d{2}\)?[\s]*$")


@dataclass
class TableClassification:
    table_index: int
    is_fee_table: bool
    score: int
    reason: str


def classify_table(table: ExtractedTable, table_index: int = 0) -> TableClassification:
    """Classify a single table as fee-relevant or not."""
    headers_lower = " ".join(h.lower() for h in table.headers)
    score = 0
    reasons = []

    # Check headers for fee indicators
    for indicator in FEE_INDICATORS:
        if indicator in headers_lower:
            score += 1
            reasons.append(f"+header:{indicator}")

    # Check headers for non-fee indicators
    for indicator in NON_FEE_INDICATORS:
        if indicator in headers_lower:
            score -= 2
            reasons.append(f"-header:{indicator}")

    # Check if cells contain dollar amounts (per-contract format: $0.XX)
    dollar_cells = 0
    total_cells = 0
    for row in table.rows[:5]:  # Sample first 5 rows
        for cell in row:
            total_cells += 1
            if DOLLAR_PATTERN.match(str(cell).strip()):
                dollar_cells += 1

    if dollar_cells >= 2:
        score += 1
        reasons.append(f"+dollar_cells:{dollar_cells}")

    # Empty/title-page tables (all headers blank or single giant cell)
    non_empty_headers = [h for h in table.headers if h.strip()]
    if len(non_empty_headers) <= 1 and len(table.rows) <= 2:
        score -= 3
        reasons.append("-title_page")

    # Very few rows with "per month" in cells → non-fee
    all_cells_text = " ".join(
        str(cell).lower() for row in table.rows[:5] for cell in row
    )
    if "per month" in all_cells_text or "per port" in all_cells_text:
        score -= 2
        reasons.append("-monthly_flat")

    return TableClassification(
        table_index=table_index,
        is_fee_table=score >= 1,
        score=score,
        reason="; ".join(reasons),
    )


def classify_tables(tables: list[ExtractedTable]) -> list[TableClassification]:
    """Classify all tables in a document."""
    return [classify_table(table, i) for i, table in enumerate(tables)]
```

**Step 4: Run tests to verify they pass**

Run: `pytest tests/unit/test_table_classifier.py -v`
Expected: PASS (8 tests)

**Step 5: Commit**

```bash
git add src/exnot/parser/table_classifier.py tests/unit/test_table_classifier.py
git commit -m "feat: add table classifier for fee vs non-fee tables"
```

---

## Task 4: Table Fingerprinter

Computes stable hashes from table headers for change detection.

**Files:**
- Create: `src/exnot/profiles/__init__.py`
- Create: `src/exnot/profiles/fingerprint.py`
- Create: `tests/unit/test_fingerprint.py`

**Step 1: Write the failing tests**

```python
# tests/unit/test_fingerprint.py
"""Tests for table fingerprinting."""
from exnot.parser.base import ExtractedTable
from exnot.profiles.fingerprint import (
    fingerprint_table,
    fingerprint_all_tables,
    compare_fingerprints,
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
    assert all(isinstance(fp, str) for fp in fps.values())


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
```

**Step 2: Run tests to verify they fail**

Run: `pytest tests/unit/test_fingerprint.py -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'exnot.profiles'`

**Step 3: Write minimal implementation**

```python
# src/exnot/profiles/__init__.py
"""Exchange profile system for rules-based fee extraction."""
```

```python
# src/exnot/profiles/fingerprint.py
"""Table fingerprinting for change detection."""
import hashlib
import re
from dataclasses import dataclass, field

from exnot.parser.base import ExtractedTable

# Patterns to strip from headers before fingerprinting
FOOTNOTE_REF_PATTERN = re.compile(r"\d+F\d+|\d+f\d+")
TRAILING_NUMBERS = re.compile(r"\d+$")


def _normalize_header(header: str) -> str:
    """Normalize a header for stable fingerprinting."""
    h = header.strip().lower()
    h = FOOTNOTE_REF_PATTERN.sub("", h)
    h = TRAILING_NUMBERS.sub("", h)
    h = re.sub(r"\s+", " ", h).strip()
    return h


def fingerprint_table(table: ExtractedTable) -> str:
    """Compute a stable fingerprint from a table's header structure."""
    normalized = [_normalize_header(h) for h in table.headers]
    raw = "|".join(normalized)
    return hashlib.sha256(raw.encode()).hexdigest()[:16]


def fingerprint_all_tables(
    tables: list[ExtractedTable],
) -> dict[str, int]:
    """Compute fingerprints for all tables. Returns {fingerprint: table_index}."""
    result = {}
    for i, table in enumerate(tables):
        fp = fingerprint_table(table)
        result[fp] = i
    return result


@dataclass
class FingerprintComparison:
    """Result of comparing current fingerprints against stored profile."""

    all_match: bool
    matched_indices: list[int] = field(default_factory=list)
    changed_indices: list[int] = field(default_factory=list)
    new_indices: list[int] = field(default_factory=list)
    removed_fingerprints: list[str] = field(default_factory=list)

    @property
    def changed_ratio(self) -> float:
        total = len(self.matched_indices) + len(self.changed_indices) + len(self.new_indices)
        if total == 0:
            return 1.0
        return (len(self.changed_indices) + len(self.new_indices)) / total


def compare_fingerprints(
    stored: dict[str, dict],
    current: dict[str, int],
) -> FingerprintComparison:
    """Compare current table fingerprints against a stored profile.

    Args:
        stored: {fingerprint: {"table_index": N, ...}} from profile
        current: {fingerprint: table_index} from current document
    """
    stored_fps = set(stored.keys())
    current_fps = set(current.keys())

    matched_fps = stored_fps & current_fps
    removed_fps = stored_fps - current_fps
    new_fps = current_fps - stored_fps

    matched_indices = [current[fp] for fp in matched_fps]
    new_indices = [current[fp] for fp in new_fps]

    # Changed = stored fee tables whose fingerprint disappeared
    # (the table at that index now has a different fingerprint)
    changed_indices = []
    for fp in removed_fps:
        old_idx = stored[fp].get("table_index")
        if old_idx is not None and stored[fp].get("is_fee_table", True):
            changed_indices.append(old_idx)

    all_match = len(removed_fps) == 0 and len(new_fps) == 0

    return FingerprintComparison(
        all_match=all_match,
        matched_indices=sorted(matched_indices),
        changed_indices=sorted(changed_indices),
        new_indices=sorted(new_indices),
        removed_fingerprints=sorted(removed_fps),
    )
```

**Step 4: Run tests to verify they pass**

Run: `pytest tests/unit/test_fingerprint.py -v`
Expected: PASS (9 tests)

**Step 5: Commit**

```bash
git add src/exnot/profiles/__init__.py src/exnot/profiles/fingerprint.py tests/unit/test_fingerprint.py
git commit -m "feat: add table fingerprinting for change detection"
```

---

## Task 5: Profile Extractor (Rules-Based)

Extracts fees from tables using stored column mappings — no AI.

**Files:**
- Create: `src/exnot/profiles/extractor.py`
- Create: `tests/unit/test_profile_extractor.py`

**Step 1: Write the failing tests**

```python
# tests/unit/test_profile_extractor.py
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
    assert len(fees) == 6  # 3 rows × 2 columns

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
    assert len(fees) == 4  # 1 row × 4 columns (2 security classes × 2 fee types)

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
```

**Step 2: Run tests to verify they fail**

Run: `pytest tests/unit/test_profile_extractor.py -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'exnot.profiles.extractor'`

**Step 3: Write minimal implementation**

```python
# src/exnot/profiles/extractor.py
"""Rules-based fee extraction using stored table profiles."""
import logging
import re
from decimal import Decimal, InvalidOperation

from exnot.parser.base import ExtractedTable

logger = logging.getLogger(__name__)

# Contra-party label normalization
CONTRA_MAPPINGS = {
    "non-customer": "NON_CUSTOMER",
    "customer": "CUSTOMER",
    "professional": "PROFESSIONAL",
    "market maker": "MARKET_MAKER",
    "mm": "MARKET_MAKER",
    "firm": "FIRM",
    "broker-dealer": "BROKER_DEALER",
    "bd": "BROKER_DEALER",
}


def parse_amount(raw: str) -> float | None:
    """Parse a dollar amount string. Returns None if unparseable."""
    if not raw or not raw.strip():
        return None

    s = raw.strip()
    # Remove dollar sign
    s = s.replace("$", "")

    # Handle parenthetical negatives: (0.20) → -0.20
    negative = False
    if s.startswith("(") and s.endswith(")"):
        negative = True
        s = s[1:-1]
    elif s.startswith("-"):
        negative = True
        s = s[1:]

    # Remove commas
    s = s.replace(",", "").strip()

    try:
        value = float(s)
    except (ValueError, InvalidOperation):
        return None

    return -value if negative else value


def _resolve_contra(raw: str | None) -> str | None:
    """Resolve a contra-party label to canonical enum."""
    if not raw:
        return None
    normalized = raw.strip().lower()
    for label, enum_val in CONTRA_MAPPINGS.items():
        if label in normalized:
            return enum_val
    return None


def extract_from_mapping(
    table: ExtractedTable,
    mapping: dict,
) -> list[dict]:
    """Extract fees from a table using a stored column mapping.

    Returns list of fee dicts in the same format as AI extraction output.
    """
    fees = []
    row_axis_col = mapping.get("row_axis_col", 0)
    has_contra = mapping.get("has_contra_party_column", False)
    contra_col = mapping.get("contra_party_col_index")
    row_mappings = mapping.get("row_mappings", {})
    section_ref = mapping.get("section_ref", "")
    order_type = mapping.get("order_type", "SIMPLE")

    for row in table.rows:
        if len(row) <= row_axis_col:
            continue

        row_label = str(row[row_axis_col]).strip()
        # Clean newlines from row labels
        row_label = re.sub(r"\s+", " ", row_label)

        participant_info = row_mappings.get(row_label)
        if not participant_info:
            # Try partial match for labels with extra text
            for known_label, info in row_mappings.items():
                if known_label.lower() in row_label.lower():
                    participant_info = info
                    break
        if not participant_info:
            continue

        contra_party = None
        if has_contra and contra_col is not None and contra_col < len(row):
            contra_party = _resolve_contra(str(row[contra_col]))

        for group in mapping.get("column_groups", []):
            security_class = group.get("security_class", "ALL")
            for col_def in group.get("columns", []):
                col_idx = col_def["col_index"]
                if col_idx >= len(row):
                    continue

                amount = parse_amount(str(row[col_idx]))
                if amount is None:
                    continue

                fees.append({
                    "participant_type": participant_info["participant_type"],
                    "contra_party_type": contra_party,
                    "security_class": security_class,
                    "fee_type": col_def["fee_type"],
                    "order_type": order_type,
                    "amount": amount,
                    "is_rebate": amount < 0,
                    "section_ref": section_ref,
                    "fee_code": None,
                    "symbol": None,
                    "fee_unit": "PER_CONTRACT",
                    "routing_destination": None,
                    "tier_group": None,
                    "tier_number": None,
                    "tier_conditions": None,
                    "conditions": None,
                    "notes": None,
                })

    return fees


def extract_all_from_profile(
    tables: list[ExtractedTable],
    table_mappings: list[dict],
) -> list[dict]:
    """Extract fees from all tables using stored profile mappings."""
    all_fees = []
    for mapping in table_mappings:
        if not mapping.get("is_fee_table", False):
            continue
        idx = mapping.get("table_index", -1)
        if idx < 0 or idx >= len(tables):
            logger.warning(f"Table index {idx} out of range (have {len(tables)} tables)")
            continue
        fees = extract_from_mapping(tables[idx], mapping)
        all_fees.extend(fees)
    return all_fees
```

**Step 4: Run tests to verify they pass**

Run: `pytest tests/unit/test_profile_extractor.py -v`
Expected: PASS (7 tests)

**Step 5: Commit**

```bash
git add src/exnot/profiles/extractor.py tests/unit/test_profile_extractor.py
git commit -m "feat: add rules-based profile extractor"
```

---

## Task 6: Profile Builder

After AI extraction, reverse-engineers which table cell each fee came from and builds column mappings.

**Files:**
- Create: `src/exnot/profiles/builder.py`
- Create: `tests/unit/test_profile_builder.py`

**Step 1: Write the failing tests**

```python
# tests/unit/test_profile_builder.py
"""Tests for profile builder — learns table mappings from AI extraction."""
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
```

**Step 2: Run tests to verify they fail**

Run: `pytest tests/unit/test_profile_builder.py -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'exnot.profiles.builder'`

**Step 3: Write minimal implementation**

```python
# src/exnot/profiles/builder.py
"""Profile builder — learns table mappings from AI extraction output."""
import logging
import re
from dataclasses import dataclass, field

from exnot.parser.base import ExtractedTable
from exnot.parser.table_classifier import classify_tables
from exnot.profiles.extractor import parse_amount
from exnot.profiles.fingerprint import fingerprint_table

logger = logging.getLogger(__name__)

# Known row labels → participant_type mappings
PARTICIPANT_LABELS = {
    "public customer": "CUSTOMER",
    "priority customer": "CUSTOMER",
    "customer": "CUSTOMER",
    "retail": "CUSTOMER",
    "professional": "PROFESSIONAL",
    "professional customer": "PROFESSIONAL",
    "market maker": "MARKET_MAKER",
    "specialist": "MARKET_MAKER",
    "mm": "MARKET_MAKER",
    "lmm": "MARKET_MAKER",
    "dpm": "MARKET_MAKER",
    "away market maker": "AWAY_MARKET_MAKER",
    "firm": "FIRM",
    "proprietary": "FIRM",
    "broker-dealer": "BROKER_DEALER",
    "broker dealer": "BROKER_DEALER",
    "bd": "BROKER_DEALER",
    "non-customer": "NON_CUSTOMER",
}


@dataclass
class BuildResult:
    """Result of profile building."""
    table_mappings: list[dict] = field(default_factory=list)
    table_fingerprints: dict = field(default_factory=dict)
    extraction_stats: dict = field(default_factory=dict)
    match_ratio: float = 0.0
    matched_fees: int = 0
    total_fees: int = 0


class ProfileBuilder:
    """Learns table column mappings from AI extraction output."""

    def build(
        self,
        tables: list[ExtractedTable],
        ai_fees: list[dict],
    ) -> BuildResult:
        """Build a profile by matching AI-extracted fees to source table cells.

        Args:
            tables: Parsed tables from the document
            ai_fees: Fee dicts returned by AI extraction
        """
        result = BuildResult(total_fees=len(ai_fees))
        if not ai_fees or not tables:
            return result

        # Classify and fingerprint tables
        classifications = classify_tables(tables)
        fingerprints = {}
        for i, table in enumerate(tables):
            fp = fingerprint_table(table)
            is_fee = classifications[i].is_fee_table
            fingerprints[fp] = {
                "table_index": i,
                "title": table.title,
                "is_fee_table": is_fee,
            }
        result.table_fingerprints = fingerprints

        # Build amount→(table_idx, row_idx, col_idx) index for fee tables
        cell_index: dict[float, list[tuple[int, int, int]]] = {}
        for tbl_idx, table in enumerate(tables):
            if not classifications[tbl_idx].is_fee_table:
                continue
            for row_idx, row in enumerate(table.rows):
                for col_idx, cell in enumerate(row):
                    amt = parse_amount(str(cell))
                    if amt is not None:
                        cell_index.setdefault(amt, []).append((tbl_idx, row_idx, col_idx))

        # Match each AI fee to a source cell
        # Track: for each table, which (row_label, col_idx) → fee mapping
        table_matches: dict[int, dict] = {}  # tbl_idx → {col_idx: [fee_info], row_labels: {label: participant}}
        matched = 0

        for fee in ai_fees:
            amount = fee.get("amount")
            if amount is None:
                continue
            # Normalize: AI sometimes returns int for 0
            amount = float(amount)

            candidates = cell_index.get(amount, [])
            if not candidates:
                continue

            # Pick best candidate — prefer tables that already have matches
            best = None
            for tbl_idx, row_idx, col_idx in candidates:
                if tbl_idx in table_matches:
                    best = (tbl_idx, row_idx, col_idx)
                    break
            if best is None:
                best = candidates[0]

            tbl_idx, row_idx, col_idx = best
            table = tables[tbl_idx]
            row = table.rows[row_idx]

            if tbl_idx not in table_matches:
                table_matches[tbl_idx] = {"columns": {}, "row_labels": {}, "fees": []}

            # Record row label mapping
            row_label = str(row[0]).strip()
            row_label = re.sub(r"\s+", " ", row_label)
            participant = fee.get("participant_type")
            if participant and row_label:
                table_matches[tbl_idx]["row_labels"][row_label] = {
                    "participant_type": participant
                }

            # Record column mapping
            col_key = col_idx
            if col_key not in table_matches[tbl_idx]["columns"]:
                header = table.headers[col_idx] if col_idx < len(table.headers) else ""
                table_matches[tbl_idx]["columns"][col_key] = {
                    "header": re.sub(r"\s+", " ", header).strip(),
                    "fee_type": fee.get("fee_type", "TRANSACTION"),
                    "col_index": col_idx,
                    "security_class": fee.get("security_class", "ALL"),
                }

            table_matches[tbl_idx]["fees"].append(fee)
            matched += 1

        result.matched_fees = matched
        result.match_ratio = matched / len(ai_fees) if ai_fees else 0.0

        # Build table_mappings from matches
        for tbl_idx, match_data in table_matches.items():
            table = tables[tbl_idx]

            # Group columns by security_class
            col_groups: dict[str, list[dict]] = {}
            for col_info in match_data["columns"].values():
                sc = col_info["security_class"]
                col_groups.setdefault(sc, []).append(col_info)

            column_groups = []
            for sc, cols in col_groups.items():
                column_groups.append({
                    "label": sc,
                    "security_class": sc,
                    "columns": [
                        {"header": c["header"], "fee_type": c["fee_type"], "col_index": c["col_index"]}
                        for c in sorted(cols, key=lambda x: x["col_index"])
                    ],
                })

            # Detect contra-party column
            has_contra = False
            contra_col = None
            sample_fee = match_data["fees"][0] if match_data["fees"] else {}
            if sample_fee.get("contra_party_type"):
                # Look for a "contra" column header
                for ci, h in enumerate(table.headers):
                    if "contra" in h.lower():
                        has_contra = True
                        contra_col = ci
                        break

            mapping = {
                "table_index": tbl_idx,
                "fingerprint": fingerprint_table(table),
                "table_title": table.title or f"Table {tbl_idx + 1}",
                "is_fee_table": True,
                "layout": "GRID",
                "row_axis_col": 0,
                "has_contra_party_column": has_contra,
                "contra_party_col_index": contra_col,
                "column_groups": column_groups,
                "row_mappings": match_data["row_labels"],
                "section_ref": sample_fee.get("section_ref", ""),
                "order_type": sample_fee.get("order_type", "SIMPLE"),
            }
            result.table_mappings.append(mapping)

        # Also add non-fee table entries (so we know to skip them)
        for i, cls in enumerate(classifications):
            if i not in table_matches:
                fp = fingerprint_table(tables[i])
                result.table_mappings.append({
                    "table_index": i,
                    "fingerprint": fp,
                    "table_title": tables[i].title or f"Table {i + 1}",
                    "is_fee_table": False,
                })

        # Extraction stats
        participant_types = sorted(set(f.get("participant_type", "") for f in ai_fees if f.get("participant_type")))
        order_types = sorted(set(f.get("order_type", "") for f in ai_fees if f.get("order_type")))
        fee_types = sorted(set(f.get("fee_type", "") for f in ai_fees if f.get("fee_type")))

        result.extraction_stats = {
            "expected_fee_count": len(ai_fees),
            "participant_types": participant_types,
            "order_types": order_types,
            "fee_types": fee_types,
            "has_tiers": any(f.get("tier_group") for f in ai_fees),
            "tier_groups": sorted(set(f.get("tier_group", "") for f in ai_fees if f.get("tier_group"))),
        }

        logger.info(
            f"Profile built: {matched}/{len(ai_fees)} fees matched to table cells "
            f"({result.match_ratio:.0%}), {len(table_matches)} fee tables identified"
        )
        return result
```

**Step 4: Run tests to verify they pass**

Run: `pytest tests/unit/test_profile_builder.py -v`
Expected: PASS (3 tests)

**Step 5: Commit**

```bash
git add src/exnot/profiles/builder.py tests/unit/test_profile_builder.py
git commit -m "feat: add profile builder - learns table mappings from AI extraction"
```

---

## Task 7: ExchangeProfile Repository

**Files:**
- Modify: `src/exnot/db/repositories.py`
- Create: `tests/unit/test_profile_repository.py`

**Step 1: Write the failing test**

```python
# tests/unit/test_profile_repository.py
"""Tests for ExchangeProfileRepository (import-only, no DB)."""
from exnot.db.repositories import ExchangeProfileRepository


def test_repository_class_exists():
    """Verify the repository class can be imported."""
    assert ExchangeProfileRepository is not None
```

**Step 2: Run test to verify it fails**

Run: `pytest tests/unit/test_profile_repository.py -v`
Expected: FAIL with `ImportError: cannot import name 'ExchangeProfileRepository'`

**Step 3: Write minimal implementation**

Add to `src/exnot/db/repositories.py`:

```python
class ExchangeProfileRepository:
    """Data access for exchange profiles."""

    def __init__(self, session):
        self.session = session

    async def get_by_exchange_id(self, exchange_id: uuid.UUID) -> ExchangeProfile | None:
        stmt = select(ExchangeProfile).where(ExchangeProfile.exchange_id == exchange_id)
        result = await self.session.execute(stmt)
        return result.scalar_one_or_none()

    async def get_by_exchange_code(self, code: str) -> ExchangeProfile | None:
        stmt = (
            select(ExchangeProfile)
            .join(Exchange)
            .where(Exchange.code == code)
        )
        result = await self.session.execute(stmt)
        return result.scalar_one_or_none()

    async def create(self, profile: ExchangeProfile) -> ExchangeProfile:
        self.session.add(profile)
        await self.session.flush()
        return profile

    async def update(self, profile: ExchangeProfile) -> ExchangeProfile:
        await self.session.flush()
        return profile
```

Import `ExchangeProfile` from models at the top of repositories.py.

**Step 4: Run test to verify it passes**

Run: `pytest tests/unit/test_profile_repository.py -v`
Expected: PASS

**Step 5: Commit**

```bash
git add src/exnot/db/repositories.py tests/unit/test_profile_repository.py
git commit -m "feat: add ExchangeProfileRepository"
```

---

## Task 8: AI Extractor Pre-filtering (Level 1 Optimization)

Modify the AI extractor to skip non-fee tables, reducing input tokens ~30-50%.

**Files:**
- Modify: `src/exnot/parser/ai_extractor.py`
- Create: `tests/unit/test_ai_extractor_prefilter.py`

**Step 1: Write the failing test**

```python
# tests/unit/test_ai_extractor_prefilter.py
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
```

**Step 2: Run test to verify it fails**

Run: `pytest tests/unit/test_ai_extractor_prefilter.py -v`
Expected: FAIL (currently _build_document_context includes all tables)

**Step 3: Modify implementation**

In `src/exnot/parser/ai_extractor.py`, update `_build_document_context`:

```python
def _build_document_context(self, document: ExtractedDocument) -> str:
    """Build a compact document context string for AI calls."""
    from exnot.parser.table_classifier import classify_tables

    # Truncate full text (large PDFs like BOX can be 50K+ chars)
    full_text = document.full_text[:60000]

    # Classify tables and only include fee-relevant ones
    classifications = classify_tables(document.tables) if document.tables else []

    # Build table text with row limits, skipping non-fee tables
    tables_text = ""
    fee_table_count = 0
    for i, table in enumerate(document.tables):
        is_fee = classifications[i].is_fee_table if i < len(classifications) else True
        if not is_fee:
            continue
        fee_table_count += 1
        tables_text += f"\n--- Table {i + 1}: {table.title} ---\n"
        tables_text += f"Headers: {table.headers}\n"
        rows_to_send = table.rows[:MAX_TABLE_ROWS]
        for row in rows_to_send:
            tables_text += f"  {row}\n"
        if len(table.rows) > MAX_TABLE_ROWS:
            tables_text += f"  ... ({len(table.rows)} total rows, showing first {MAX_TABLE_ROWS})\n"
        if table.footnotes:
            tables_text += f"Footnotes: {table.footnotes}\n"

    return f"DOCUMENT TEXT:\n{full_text}\n\nEXTRACTED TABLES ({fee_table_count} fee-relevant):\n{tables_text}"
```

**Step 4: Run test to verify it passes**

Run: `pytest tests/unit/test_ai_extractor_prefilter.py -v`
Expected: PASS

**Step 5: Run full test suite**

Run: `pytest tests/ -v`
Expected: All existing tests still pass

**Step 6: Commit**

```bash
git add src/exnot/parser/ai_extractor.py tests/unit/test_ai_extractor_prefilter.py
git commit -m "feat: pre-filter non-fee tables from AI extraction context"
```

---

## Task 9: Pipeline Integration — Profile-Aware Routing

Wire everything together in the main pipeline.

**Files:**
- Modify: `src/exnot/workers/pipelines.py`

**Step 1: Read the current pipeline**

Read `src/exnot/workers/pipelines.py` to understand where to add profile-aware routing. The key insertion point is after document parsing (step d/e) and before AI extraction. Look for the call to `AIExtractor().extract(extracted_doc, exchange_code)`.

**Step 2: Add profile-aware routing**

Add a new function `_try_profile_extraction` and modify `run_scrape_pipeline` to call it before falling back to AI:

```python
def _try_profile_extraction(
    exchange: Exchange,
    document: ExtractedDocument,
    session,
) -> list[dict] | None:
    """Attempt rules-based extraction using stored profile.

    Returns list of fee dicts if profile extraction succeeds, None if AI needed.
    """
    from exnot.db.models import ExchangeProfile, ProfileStatus
    from exnot.profiles.extractor import extract_all_from_profile
    from exnot.profiles.fingerprint import (
        compare_fingerprints,
        fingerprint_all_tables,
    )

    # Load profile
    profile = session.query(ExchangeProfile).filter_by(exchange_id=exchange.id).first()
    if not profile or profile.status != ProfileStatus.ACTIVE:
        logger.info(f"[{exchange.code}] No active profile, will use AI extraction")
        return None

    # Compare fingerprints
    current_fps = fingerprint_all_tables(document.tables)
    comparison = compare_fingerprints(profile.table_fingerprints, current_fps)

    if not comparison.all_match:
        changed_pct = comparison.changed_ratio
        if changed_pct > 0.5:
            logger.info(
                f"[{exchange.code}] Major table structure change ({changed_pct:.0%}), "
                f"rebuilding profile with AI"
            )
            profile.status = ProfileStatus.NEEDS_UPDATE
            return None
        else:
            logger.info(
                f"[{exchange.code}] Minor table changes detected "
                f"({len(comparison.changed_indices)} tables changed), "
                f"falling back to AI for this run"
            )
            profile.status = ProfileStatus.NEEDS_UPDATE
            return None

    # All fingerprints match — rules-based extraction
    logger.info(f"[{exchange.code}] All table fingerprints match profile, using rules-based extraction")
    fees = extract_all_from_profile(document.tables, profile.table_mappings)
    logger.info(f"[{exchange.code}] Profile extraction: {len(fees)} fees (expected {profile.extraction_stats.get('expected_fee_count', '?')})")

    return fees


def _build_and_save_profile(
    exchange: Exchange,
    document: ExtractedDocument,
    ai_fees: list[dict],
    session,
):
    """Build a profile from AI extraction and save it."""
    from exnot.db.models import ExchangeProfile, ProfileStatus
    from exnot.profiles.builder import ProfileBuilder

    builder = ProfileBuilder()
    result = builder.build(document.tables, ai_fees)

    # Only save as ACTIVE if match ratio is good
    status = ProfileStatus.ACTIVE if result.match_ratio >= 0.7 else ProfileStatus.LEARNING

    # Check if profile already exists
    profile = session.query(ExchangeProfile).filter_by(exchange_id=exchange.id).first()
    if profile:
        profile.table_mappings = result.table_mappings
        profile.table_fingerprints = result.table_fingerprints
        profile.extraction_stats = result.extraction_stats
        profile.status = status
        profile.profile_version += 1
    else:
        profile = ExchangeProfile(
            exchange_id=exchange.id,
            profile_version=1,
            table_mappings=result.table_mappings,
            table_fingerprints=result.table_fingerprints,
            section_metadata={},
            extraction_stats=result.extraction_stats,
            status=status,
        )
        session.add(profile)

    logger.info(
        f"[{exchange.code}] Profile {'updated' if profile.profile_version > 1 else 'created'}: "
        f"status={status.value}, match_ratio={result.match_ratio:.0%}, "
        f"v{profile.profile_version}"
    )
```

**Step 3: Modify the main pipeline to use profiles**

In `run_scrape_pipeline`, after document parsing and before AI extraction, add:

```python
# --- Step (new): Try profile-based extraction ---
profile_fees = _try_profile_extraction(exchange, extracted_doc, session)

if profile_fees is not None:
    # Rules-based extraction succeeded — skip AI
    raw_fees = profile_fees
    # Still need to normalize
    from exnot.normalizer.engine import NormalizationEngine
    engine = NormalizationEngine()
    normalized = engine.normalize_from_raw_fees(raw_fees, exchange.code)
    # ... (save normalized fees, detect changes, etc.)
else:
    # AI extraction (existing code)
    extractor = AIExtractor()
    extraction_result = extractor.extract(extracted_doc, exchange.code)
    # ... existing normalization/save code ...

    # Build/update profile from AI results
    _build_and_save_profile(exchange, extracted_doc, extraction_result.raw_fees, session)
```

The exact integration depends on the current pipeline structure. Read `pipelines.py` carefully to find the right insertion points. The key principle: profile extraction is tried FIRST. If it returns fees, skip AI entirely. If it returns None, fall through to existing AI extraction, then build/update the profile.

**Step 4: Verify with existing tests**

Run: `pytest tests/ -v`
Expected: All tests pass (pipeline changes are additive, no behavior change when no profile exists)

**Step 5: Commit**

```bash
git add src/exnot/workers/pipelines.py
git commit -m "feat: profile-aware pipeline routing - rules extraction before AI"
```

---

## Task 10: End-to-End Verification

**Step 1: Run migration**

```bash
docker compose exec web alembic upgrade head
```

**Step 2: Rebuild Docker**

```bash
docker compose build && docker compose up -d
```

**Step 3: Run all unit tests**

```bash
pytest tests/ -v
```
Expected: All tests pass

**Step 4: Test first-run profile building**

Delete CBOE_BZX snapshot to force re-extraction:

```bash
docker compose exec db psql -U exnot -d exnot -c "
DELETE FROM fee_changes WHERE exchange_id = (SELECT id FROM exchanges WHERE code='CBOE_BZX');
DELETE FROM normalized_fees WHERE snapshot_id IN (SELECT id FROM fee_schedule_snapshots WHERE exchange_id = (SELECT id FROM exchanges WHERE code='CBOE_BZX'));
DELETE FROM fee_tiers WHERE snapshot_id IN (SELECT id FROM fee_schedule_snapshots WHERE exchange_id = (SELECT id FROM exchanges WHERE code='CBOE_BZX'));
DELETE FROM scraped_documents WHERE snapshot_id IN (SELECT id FROM fee_schedule_snapshots WHERE exchange_id = (SELECT id FROM exchanges WHERE code='CBOE_BZX'));
DELETE FROM fee_schedule_snapshots WHERE exchange_id = (SELECT id FROM exchanges WHERE code='CBOE_BZX');
"
```

Trigger extraction:

```bash
docker compose exec web python -c "
from exnot.workers.tasks import scrape_and_process_exchange
scrape_and_process_exchange.delay('CBOE_BZX')
"
```

Check worker logs for:
- `[CBOE_BZX] No active profile, will use AI extraction` (first run)
- `[CBOE_BZX] Profile created: status=ACTIVE, match_ratio=XX%`

Verify profile exists:

```bash
docker compose exec db psql -U exnot -d exnot -c "
SELECT e.code, p.status, p.profile_version,
       jsonb_array_length(p.table_mappings) as mapping_count,
       p.extraction_stats->>'expected_fee_count' as expected_fees
FROM exchange_profiles p
JOIN exchanges e ON p.exchange_id = e.id;
"
```

**Step 5: Test second-run profile extraction**

Delete snapshot again (keep the profile):

```bash
docker compose exec db psql -U exnot -d exnot -c "
DELETE FROM fee_changes WHERE exchange_id = (SELECT id FROM exchanges WHERE code='CBOE_BZX');
DELETE FROM normalized_fees WHERE snapshot_id IN (SELECT id FROM fee_schedule_snapshots WHERE exchange_id = (SELECT id FROM exchanges WHERE code='CBOE_BZX'));
DELETE FROM fee_tiers WHERE snapshot_id IN (SELECT id FROM fee_schedule_snapshots WHERE exchange_id = (SELECT id FROM exchanges WHERE code='CBOE_BZX'));
DELETE FROM scraped_documents WHERE snapshot_id IN (SELECT id FROM fee_schedule_snapshots WHERE exchange_id = (SELECT id FROM exchanges WHERE code='CBOE_BZX'));
DELETE FROM fee_schedule_snapshots WHERE exchange_id = (SELECT id FROM exchanges WHERE code='CBOE_BZX');
"
```

Trigger extraction again:

```bash
docker compose exec web python -c "
from exnot.workers.tasks import scrape_and_process_exchange
scrape_and_process_exchange.delay('CBOE_BZX')
"
```

Check worker logs for:
- `[CBOE_BZX] All table fingerprints match profile, using rules-based extraction`
- `[CBOE_BZX] Profile extraction: XX fees`
- NO AI API calls (no `HTTP Request: POST https://api.anthropic.com`)

Compare fee counts between AI-extracted and profile-extracted runs — they should be close (exact match not required since profile only covers matched tables).

**Step 6: Final commit**

```bash
git add -A
git commit -m "feat: smart extraction pipeline - profile-based rules extraction"
git push origin qa
```
