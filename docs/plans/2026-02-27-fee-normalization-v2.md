# Fee Normalization V2 Implementation Plan

> **For Claude:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task.

**Goal:** Replace the oversimplified fee normalization model with a full-fidelity schema that captures contra-party dependencies, fee codes, multi-condition volume tiers, symbol-specific pricing, routing destinations, and exchange-family-specific extraction logic.

**Architecture:** Relational core columns for cross-exchange-queryable dimensions (participant, security class, fee type, amount) plus JSONB `conditions` column for exchange-specific complexity. Separate `FeeTier` table for volume-tiered pricing with structured condition logic. Exchange-family-specific AI extraction prompts replace the single generic prompt.

**Tech Stack:** PostgreSQL (existing), SQLAlchemy 2.x ORM, Alembic migrations, Pydantic v2, Anthropic Claude API

---

## Task 1: Expand Enums in DB Models

**Files:**
- Modify: `src/exnot/db/models.py:49-84` (existing enum definitions)

**Step 1: Add new enum values to existing enums and create FeeUnit enum**

In `src/exnot/db/models.py`, update the four existing enums and add one new enum:

```python
class ParticipantType(str, enum.Enum):
    CUSTOMER = "CUSTOMER"
    PROFESSIONAL = "PROFESSIONAL"
    MARKET_MAKER = "MARKET_MAKER"
    AWAY_MARKET_MAKER = "AWAY_MARKET_MAKER"
    FIRM = "FIRM"
    BROKER_DEALER = "BROKER_DEALER"
    NON_CUSTOMER = "NON_CUSTOMER"
    ALL = "ALL"


class SecurityClass(str, enum.Enum):
    PENNY = "PENNY"
    NON_PENNY = "NON_PENNY"
    INDEX = "INDEX"
    ETF = "ETF"
    EQUITY = "EQUITY"
    MINI = "MINI"
    SPY = "SPY"
    QQQ = "QQQ"
    IWM = "IWM"
    NDX = "NDX"
    RUT = "RUT"
    VIX = "VIX"
    ALL = "ALL"


class OrderType(str, enum.Enum):
    SIMPLE = "SIMPLE"
    COMPLEX = "COMPLEX"
    AUCTION = "AUCTION"
    DIRECTED = "DIRECTED"
    QCC = "QCC"
    PIM = "PIM"
    CROSSING = "CROSSING"
    FLEX = "FLEX"
    OPENING = "OPENING"
    ROUTED = "ROUTED"
    ALL = "ALL"


class FeeType(str, enum.Enum):
    MAKER = "MAKER"
    TAKER = "TAKER"
    ROUTING = "ROUTING"
    ORF = "ORF"
    TRANSACTION = "TRANSACTION"
    CLEARING = "CLEARING"
    CONNECTIVITY = "CONNECTIVITY"
    MARKET_DATA = "MARKET_DATA"
    MEMBERSHIP = "MEMBERSHIP"
    CROSSING_FEE = "CROSSING_FEE"
    PIM_FEE = "PIM_FEE"
    RESPONSE_FEE = "RESPONSE_FEE"
    BREAK_UP_REBATE = "BREAK_UP_REBATE"
    SURCHARGE = "SURCHARGE"
    CANCELLATION = "CANCELLATION"
    STOCK_HANDLING = "STOCK_HANDLING"


class FeeUnit(str, enum.Enum):
    PER_CONTRACT = "PER_CONTRACT"
    PER_CONTRACT_SIDE = "PER_CONTRACT_SIDE"
    PER_SHARE = "PER_SHARE"
    MONTHLY_FLAT = "MONTHLY_FLAT"
    PER_PORT_MONTHLY = "PER_PORT_MONTHLY"
    PERCENTAGE = "PERCENTAGE"
    PER_ORDER = "PER_ORDER"
```

**Step 2: Commit**

```bash
git add src/exnot/db/models.py
git commit -m "feat: expand fee enums with new participant types, security classes, order types, fee types, and FeeUnit"
```

---

## Task 2: Add FeeTier Model and Update NormalizedFee Model

**Files:**
- Modify: `src/exnot/db/models.py:181-209` (NormalizedFee model)

**Step 1: Add FeeTier model after the NormalizedFee class**

Add this new model in `src/exnot/db/models.py` right after NormalizedFee. Also update NormalizedFee to add the new columns.

Replace the existing `NormalizedFee` class (lines 181-209) with:

```python
class NormalizedFee(Base):
    __tablename__ = "normalized_fees"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    snapshot_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("fee_schedule_snapshots.id"), nullable=False, index=True
    )
    exchange_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("exchanges.id"), nullable=False, index=True
    )
    # Core dimensions
    fee_code: Mapped[str | None] = mapped_column(String(20), nullable=True)
    participant_type: Mapped[ParticipantType] = mapped_column(
        Enum(ParticipantType), nullable=False
    )
    contra_party_type: Mapped[ParticipantType | None] = mapped_column(
        Enum(ParticipantType, name="contra_participant_type"), nullable=True
    )
    security_class: Mapped[SecurityClass] = mapped_column(Enum(SecurityClass), nullable=False)
    symbol: Mapped[str | None] = mapped_column(String(20), nullable=True)
    order_type: Mapped[OrderType] = mapped_column(Enum(OrderType), nullable=False)
    fee_type: Mapped[FeeType] = mapped_column(Enum(FeeType), nullable=False)
    fee_unit: Mapped[FeeUnit] = mapped_column(
        Enum(FeeUnit), nullable=False, server_default="PER_CONTRACT"
    )
    amount_cents: Mapped[int] = mapped_column(
        Integer, nullable=False, comment="Fee in hundredths of a cent for precision"
    )
    is_rebate: Mapped[bool] = mapped_column(Boolean, default=False)
    # Tier linkage
    tier_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("fee_tiers.id"), nullable=True
    )
    # Routing
    routing_destination: Mapped[str | None] = mapped_column(String(200), nullable=True)
    # Conditions & metadata
    conditions: Mapped[dict | None] = mapped_column(JSONB, nullable=True)
    effective_date: Mapped[date | None] = mapped_column(Date, nullable=True)
    expiry_date: Mapped[date | None] = mapped_column(Date, nullable=True)
    section_ref: Mapped[str | None] = mapped_column(String(50), nullable=True)
    notes: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now())

    # Keep old columns for migration compatibility (will be dropped later)
    volume_tier: Mapped[str | None] = mapped_column(String(100), nullable=True)
    tier_threshold_pct: Mapped[float | None] = mapped_column(Float, nullable=True)
    tier_threshold_contracts: Mapped[int | None] = mapped_column(Integer, nullable=True)

    snapshot: Mapped["FeeScheduleSnapshot"] = relationship(back_populates="normalized_fees")
    exchange: Mapped["Exchange"] = relationship(back_populates="normalized_fees")
    tier: Mapped["FeeTier | None"] = relationship(back_populates="fees")


class FeeTier(Base):
    __tablename__ = "fee_tiers"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    snapshot_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("fee_schedule_snapshots.id"), nullable=False, index=True
    )
    exchange_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("exchanges.id"), nullable=False, index=True
    )
    tier_group: Mapped[str] = mapped_column(String(100), nullable=False)
    tier_number: Mapped[int] = mapped_column(Integer, nullable=False)
    tier_name: Mapped[str] = mapped_column(String(200), nullable=False)
    conditions: Mapped[dict] = mapped_column(JSONB, nullable=False)
    is_retroactive: Mapped[bool] = mapped_column(Boolean, default=True)
    notes: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now())

    snapshot: Mapped["FeeScheduleSnapshot"] = relationship()
    exchange: Mapped["Exchange"] = relationship()
    fees: Mapped[list["NormalizedFee"]] = relationship(back_populates="tier")
```

**Step 2: Commit**

```bash
git add src/exnot/db/models.py
git commit -m "feat: add FeeTier model and expand NormalizedFee with contra_party, fee_code, conditions, fee_unit"
```

---

## Task 3: Generate and Apply Alembic Migration

**Files:**
- Create: New Alembic migration (autogenerated)

**Step 1: Generate migration**

```bash
docker compose exec web alembic revision --autogenerate -m "normalization_v2_expanded_schema"
```

**Step 2: Review the generated migration**

Check that it:
- Adds new enum values to existing PostgreSQL enum types (ParticipantType, SecurityClass, OrderType, FeeType)
- Creates the `feeunit` enum type
- Creates the `fee_tiers` table
- Adds new columns to `normalized_fees`: `fee_code`, `contra_party_type`, `symbol`, `fee_unit`, `tier_id`, `routing_destination`, `conditions`, `expiry_date`, `section_ref`

**Important:** PostgreSQL doesn't support adding enum values inside transactions. The migration's `upgrade()` must use:
```python
from alembic import op
# Add enum values outside transaction
op.execute("ALTER TYPE participanttype ADD VALUE IF NOT EXISTS 'NON_CUSTOMER'")
op.execute("ALTER TYPE participanttype ADD VALUE IF NOT EXISTS 'ALL'")
# ... etc for each new enum value
```

This must be done with `autocommit=True` or in a separate migration step. If autogenerate doesn't handle this correctly, manually fix the migration.

**Step 3: Apply migration**

```bash
docker compose exec web alembic upgrade head
```

**Step 4: Verify**

```bash
docker compose exec db psql -U exnot -c "\d normalized_fees"
docker compose exec db psql -U exnot -c "\d fee_tiers"
```

**Step 5: Commit**

```bash
git add alembic/versions/
git commit -m "feat: alembic migration for normalization v2 schema"
```

---

## Task 4: Update Pydantic Schema (normalizer/schema.py)

**Files:**
- Modify: `src/exnot/normalizer/schema.py` (complete rewrite)
- Test: `tests/unit/test_normalizer.py`

**Step 1: Write failing test for new schema fields**

Add to `tests/unit/test_normalizer.py`:

```python
def test_v2_schema_fields(self):
    """Test that V2 schema supports new fields."""
    from exnot.normalizer.schema import FeeUnit, NormalizedFeeEntry

    entry = NormalizedFeeEntry(
        exchange_code="CBOE_BZX",
        fee_code="ZA",
        participant_type=ParticipantType.CUSTOMER,
        contra_party_type=ParticipantType.NON_CUSTOMER,
        security_class=SecurityClass.PENNY,
        symbol=None,
        order_type=OrderType.COMPLEX,
        fee_type=FeeType.MAKER,
        fee_unit=FeeUnit.PER_CONTRACT,
        amount=Decimal("-0.40"),
        is_rebate=True,
        routing_destination=None,
        tier_group="complex_customer_penny",
        tier_number=0,
        conditions={"footnotes": ["10"]},
        section_ref="Complex Orders",
    )
    assert entry.fee_code == "ZA"
    assert entry.contra_party_type == ParticipantType.NON_CUSTOMER
    assert entry.fee_unit == FeeUnit.PER_CONTRACT
    assert entry.conditions == {"footnotes": ["10"]}
```

**Step 2: Run test to verify it fails**

```bash
cd /home/yogidigital/projects/exnot && python -m pytest tests/unit/test_normalizer.py::TestNormalizationEngine::test_v2_schema_fields -v
```

Expected: FAIL (missing imports / fields)

**Step 3: Rewrite `src/exnot/normalizer/schema.py`**

```python
"""Canonical fee schema - Pydantic models for normalized fee data."""

from datetime import date
from decimal import Decimal
from enum import Enum

from pydantic import BaseModel, Field


class ParticipantType(str, Enum):
    CUSTOMER = "CUSTOMER"
    PROFESSIONAL = "PROFESSIONAL"
    MARKET_MAKER = "MARKET_MAKER"
    AWAY_MARKET_MAKER = "AWAY_MARKET_MAKER"
    FIRM = "FIRM"
    BROKER_DEALER = "BROKER_DEALER"
    NON_CUSTOMER = "NON_CUSTOMER"
    ALL = "ALL"


class SecurityClass(str, Enum):
    PENNY = "PENNY"
    NON_PENNY = "NON_PENNY"
    INDEX = "INDEX"
    ETF = "ETF"
    EQUITY = "EQUITY"
    MINI = "MINI"
    SPY = "SPY"
    QQQ = "QQQ"
    IWM = "IWM"
    NDX = "NDX"
    RUT = "RUT"
    VIX = "VIX"
    ALL = "ALL"


class OrderType(str, Enum):
    SIMPLE = "SIMPLE"
    COMPLEX = "COMPLEX"
    AUCTION = "AUCTION"
    DIRECTED = "DIRECTED"
    QCC = "QCC"
    PIM = "PIM"
    CROSSING = "CROSSING"
    FLEX = "FLEX"
    OPENING = "OPENING"
    ROUTED = "ROUTED"
    ALL = "ALL"


class FeeType(str, Enum):
    MAKER = "MAKER"
    TAKER = "TAKER"
    ROUTING = "ROUTING"
    ORF = "ORF"
    TRANSACTION = "TRANSACTION"
    CLEARING = "CLEARING"
    CONNECTIVITY = "CONNECTIVITY"
    MARKET_DATA = "MARKET_DATA"
    MEMBERSHIP = "MEMBERSHIP"
    CROSSING_FEE = "CROSSING_FEE"
    PIM_FEE = "PIM_FEE"
    RESPONSE_FEE = "RESPONSE_FEE"
    BREAK_UP_REBATE = "BREAK_UP_REBATE"
    SURCHARGE = "SURCHARGE"
    CANCELLATION = "CANCELLATION"
    STOCK_HANDLING = "STOCK_HANDLING"


class FeeUnit(str, Enum):
    PER_CONTRACT = "PER_CONTRACT"
    PER_CONTRACT_SIDE = "PER_CONTRACT_SIDE"
    PER_SHARE = "PER_SHARE"
    MONTHLY_FLAT = "MONTHLY_FLAT"
    PER_PORT_MONTHLY = "PER_PORT_MONTHLY"
    PERCENTAGE = "PERCENTAGE"
    PER_ORDER = "PER_ORDER"


class TierConditionCriterion(BaseModel):
    """A single criterion within a tier condition."""
    metric: str = Field(description="ADAV, ADRV, ADV, NBBO_PCT, TOTAL_VOLUME, CCV_PCT, CROSS_ASSET")
    capacities: list[str] | None = Field(default=None, description="Participant types counted")
    security_filter: str | None = None
    operator: str = Field(description=">=, <=, >, <, ==")
    value: float = Field(description="Threshold value")
    unit: str = Field(description="PCT_OCV, PCT_CCV, PCT_TCV, CONTRACTS, PERCENT")
    description: str = ""


class TierCondition(BaseModel):
    """Structured tier condition with AND/OR logic."""
    logic: str = Field(default="AND", description="AND or OR")
    criteria: list[TierConditionCriterion] = Field(default_factory=list)


class NormalizedFeeEntry(BaseModel):
    """A single normalized fee entry."""

    exchange_code: str
    fee_code: str | None = None
    participant_type: ParticipantType
    contra_party_type: ParticipantType | None = None
    security_class: SecurityClass
    symbol: str | None = None
    order_type: OrderType
    fee_type: FeeType
    fee_unit: FeeUnit = FeeUnit.PER_CONTRACT
    amount: Decimal = Field(description="Per-contract amount in USD. Negative for rebates.")
    is_rebate: bool = False
    routing_destination: str | None = None
    tier_group: str | None = None
    tier_number: int | None = None
    tier_conditions: TierCondition | None = None
    conditions: dict | None = None
    effective_date: date | None = None
    expiry_date: date | None = None
    section_ref: str | None = None
    notes: str | None = None

    # Kept for backward compatibility
    volume_tier: str | None = None
    tier_threshold_pct: float | None = None
    tier_threshold_contracts: int | None = None

    @property
    def amount_cents(self) -> int:
        """Amount in hundredths of a cent for database storage."""
        return int(self.amount * 10000)


class NormalizedFeeSchedule(BaseModel):
    """Complete normalized fee schedule for an exchange."""

    exchange_code: str
    exchange_name: str
    effective_date: date | None = None
    fees: list[NormalizedFeeEntry] = Field(default_factory=list)
    tiers: list[dict] = Field(default_factory=list, description="Tier group definitions")
    parsing_confidence: float = 0.0
    extraction_notes: str = ""

    @property
    def fee_count(self) -> int:
        return len(self.fees)

    def get_fees(
        self,
        participant_type: ParticipantType | None = None,
        security_class: SecurityClass | None = None,
        fee_type: FeeType | None = None,
        order_type: OrderType | None = None,
    ) -> list[NormalizedFeeEntry]:
        """Filter fees by criteria."""
        result = self.fees
        if participant_type:
            result = [f for f in result if f.participant_type == participant_type]
        if security_class:
            result = [f for f in result if f.security_class == security_class]
        if fee_type:
            result = [f for f in result if f.fee_type == fee_type]
        if order_type:
            result = [f for f in result if f.order_type == order_type]
        return result
```

**Step 4: Run test to verify it passes**

```bash
cd /home/yogidigital/projects/exnot && python -m pytest tests/unit/test_normalizer.py -v
```

Expected: ALL tests PASS (existing tests should still work since new fields have defaults)

**Step 5: Commit**

```bash
git add src/exnot/normalizer/schema.py tests/unit/test_normalizer.py
git commit -m "feat: expand normalizer schema with V2 fields - fee_code, contra_party, tiers, conditions"
```

---

## Task 5: Create Exchange-Family Extraction Hints

**Files:**
- Create: `src/exnot/parser/extraction_hints.py`

**Step 1: Create the extraction hints module**

Create `src/exnot/parser/extraction_hints.py` with the `EXCHANGE_FAMILY_HINTS` dict and a `get_hints_for_exchange(exchange_code: str) -> dict` function. Full content from the design doc's Section 5. Also add a function `get_exchange_family(exchange_code: str) -> str` that maps exchange codes to families.

```python
"""Exchange-family-specific extraction hints for AI fee schedule parsing."""


def get_exchange_family(exchange_code: str) -> str:
    """Map exchange code to its family."""
    for family, info in EXCHANGE_FAMILY_HINTS.items():
        if exchange_code in info.get("families", []):
            return family
    return "OTHER"


def get_hints_for_exchange(exchange_code: str) -> dict:
    """Get extraction hints for a specific exchange."""
    family = get_exchange_family(exchange_code)
    return EXCHANGE_FAMILY_HINTS.get(family, EXCHANGE_FAMILY_HINTS["OTHER"])


EXCHANGE_FAMILY_HINTS = {
    "CBOE": {
        "families": ["CBOE_BZX", "CBOE_C1", "CBOE_C2", "CBOE_EDGX"],
        "terminology": {
            "Customer": "Priority Customer",
            "Non-Customer": "Professional + MM + Firm + BD + JBO",
        },
        "key_features": [
            "Fee codes (2-letter codes like PY, PC, PM, ZA)",
            "SPY-specific rates separate from other Penny",
            "RUT index license surcharges on Non-Customer only",
            "Complex order contra-party grids (Customer-vs-Customer, Customer-vs-NonCustomer)",
            "Cross-asset tiers (BZX Equities ADAV unlocks options rebates)",
            "Multi-condition AND/OR tier logic using ADAV, ADRV, ADV as % of OCV",
            "Opening trades often free",
            "Routing fees vary by destination exchange group",
        ],
        "prompt_addition": """CBOE-SPECIFIC INSTRUCTIONS:
- Extract ALL fee codes (2-letter codes like PY, PC, PM, ZA, etc.)
- SPY often has different rates than other Penny securities — capture as symbol="SPY"
- RUT has index license surcharges — capture as fee_type="SURCHARGE" with symbol="RUT"
- Complex orders: capture contra_party_type (CUSTOMER vs NON_CUSTOMER)
- Fee codes starting with Z are complex orders, R are routed, P are penny, N are non-penny, B are RUT, O are opening
- Volume tiers reference ADAV/ADRV/ADV as % of OCV — capture exact thresholds
- Cross-asset tiers reference BZX Equities volume — capture in tier_conditions
- Opening trades (codes OO, OC, BO, GO) are typically free ($0.00)""",
    },
    "NASDAQ": {
        "families": ["NASDAQ_ISE", "NASDAQ_NOM", "NASDAQ_PHLX", "NASDAQ_GEMX",
                      "NASDAQ_MRX", "NASDAQ_NTX"],
        "terminology": {
            "Priority Customer": "Public Customer (< 390 orders/day)",
            "Professional Customer": "Professional (>= 390 orders/day)",
            "FarMM / Non-Nasdaq ISE MM": "Away Market Maker",
        },
        "key_features": [
            "MM Plus tiers based on NBBO time percentage (not volume)",
            "Priority Customer Complex tiers (up to 10 levels)",
            "Select Symbols = Penny, Non-Select Symbols = Non-Penny",
            "Linked symbol rebate programs (SPY-QQQ, SPY-IWM)",
            "PIM volume discounts (retroactive)",
            "Crossing/Solicitation rebate stacking",
            "QCC rebates with tier enhancements",
        ],
        "prompt_addition": """NASDAQ-SPECIFIC INSTRUCTIONS:
- "Select Symbols" = PENNY, "Non-Select Symbols" = NON_PENNY
- "Priority Customer" = CUSTOMER, "Professional Customer" = PROFESSIONAL
- "Non-Nasdaq ISE Market Maker" / "FarMM" = AWAY_MARKET_MAKER
- MM Plus tiers are based on NBBO time % — use metric="NBBO_PCT" in tier_conditions
- Priority Customer Complex tiers (up to 10) are based on % of Customer Total Consolidated Volume
- Capture PIM orders as order_type="PIM", Crossing/FAC/SOL as order_type="CROSSING"
- QCC and Solicitation fees may stack — note stacking in conditions
- When fees differ based on contra-party, set contra_party_type
- Section 3 = Regular Orders, Section 4 = Complex Orders, Section 5 = Index Options, Section 6 = Other""",
    },
    "MIAX": {
        "families": ["MIAX_OPTIONS", "MIAX_PEARL", "MIAX_EMERALD", "MIAX_SAPPHIRE"],
        "terminology": {
            "Priority Customer": "Public Customer",
            "PRIME": "Price Improvement Mechanism (auction)",
            "cPRIME": "Complex PRIME auction",
        },
        "key_features": [
            "Liquidity Indicator codes",
            "PRIME and cPRIME auction mechanisms",
            "Priority Customer tiered rebates (volume-based)",
        ],
        "prompt_addition": """MIAX-SPECIFIC INSTRUCTIONS:
- "Priority Customer" = CUSTOMER
- PRIME auction orders = order_type="PIM", cPRIME = order_type="PIM" with order_type note
- Capture Liquidity Indicator codes as fee_code
- Volume tiers use ADV thresholds as % of national Customer volume
- Capture PRIME/cPRIME fees separately from regular maker/taker""",
    },
    "NYSE": {
        "families": ["NYSE_ARCA", "NYSE_AMERICAN"],
        "terminology": {
            "Customer": "Public Customer",
            "Firm": "Firm / Broker-Dealer",
        },
        "key_features": [
            "Tier-based maker/taker with absolute contract thresholds",
            "Customer Penny Pilot tiers",
            "Step-up credits",
        ],
        "prompt_addition": """NYSE-SPECIFIC INSTRUCTIONS:
- Volume tiers use absolute monthly contract counts (not percentages)
- Capture step-up credits as separate fee entries with conditions
- Customer Penny Pilot tiers are common — capture all tiers
- Both NYSE Arca and NYSE American are PDF-based fee schedules""",
    },
    "OTHER": {
        "families": ["BOX_OPTIONS", "MEMX_OPTIONS"],
        "key_features": [
            "BOX: PIP auction, simpler structure",
            "MEMX: Composite fee codes [Action][Capacity][Tier][SecurityClass]",
        ],
        "prompt_addition": """EXCHANGE-SPECIFIC INSTRUCTIONS:
- Extract ALL fee codes exactly as shown in the schedule
- For MEMX: fee codes follow pattern [Action][Capacity][Tier?][SecurityClass] e.g. Dp1P
- For BOX: PIP (Price Improvement Period) = order_type="PIM"
- Capture all volume tiers with their exact conditions""",
    },
}
```

**Step 2: Commit**

```bash
git add src/exnot/parser/extraction_hints.py
git commit -m "feat: add exchange-family extraction hints for AI fee schedule parsing"
```

---

## Task 6: Rewrite AI Extractor with V2 Prompt and Family Hints

**Files:**
- Modify: `src/exnot/parser/ai_extractor.py` (update prompts and output parsing)

**Step 1: Update `FEE_EXTRACTION_PROMPT` to request V2 output schema**

Replace the existing `FEE_EXTRACTION_PROMPT` in `src/exnot/parser/ai_extractor.py` with a new prompt that:
- Requests the expanded JSON schema (fee_code, contra_party_type, symbol, fee_unit, tier_group, tier_number, tier_conditions, conditions, section_ref)
- Uses canonical enum values directly
- Includes placeholder `{exchange_hints}` for family-specific instructions

```python
FEE_EXTRACTION_PROMPT = """You are a financial data extraction specialist for US options exchange fee schedules.

Analyze the document and extract ALL fee and rebate amounts. For EVERY fee entry, provide a JSON object with these EXACT field names and enum values:

{{
  "fee_code": "<exchange billing code or null>",
  "participant_type": "CUSTOMER" | "PROFESSIONAL" | "MARKET_MAKER" | "AWAY_MARKET_MAKER" | "FIRM" | "BROKER_DEALER" | "NON_CUSTOMER" | "ALL",
  "contra_party_type": "<same enum as participant_type, or null if fee doesn't depend on contra>",
  "security_class": "PENNY" | "NON_PENNY" | "INDEX" | "EQUITY" | "ETF" | "MINI" | "SPY" | "QQQ" | "IWM" | "NDX" | "RUT" | "VIX" | "ALL",
  "symbol": "<specific symbol like SPY, NDX, RUT if the fee is symbol-specific, else null>",
  "order_type": "SIMPLE" | "COMPLEX" | "AUCTION" | "PIM" | "CROSSING" | "DIRECTED" | "QCC" | "FLEX" | "OPENING" | "ROUTED" | "ALL",
  "fee_type": "MAKER" | "TAKER" | "ROUTING" | "CROSSING_FEE" | "PIM_FEE" | "RESPONSE_FEE" | "BREAK_UP_REBATE" | "SURCHARGE" | "ORF" | "TRANSACTION" | "CLEARING" | "CONNECTIVITY" | "MARKET_DATA" | "MEMBERSHIP" | "CANCELLATION" | "STOCK_HANDLING",
  "fee_unit": "PER_CONTRACT" | "PER_CONTRACT_SIDE" | "PER_SHARE" | "MONTHLY_FLAT" | "PER_PORT_MONTHLY" | "PERCENTAGE" | "PER_ORDER",
  "amount": <decimal number in USD>,
  "is_rebate": <true if rebate/credit, false if fee>,
  "routing_destination": "<target exchange(s) for routed orders, or null>",
  "tier_group": "<group name for related tiers like 'customer_penny_add', or null if not tiered>",
  "tier_number": <0 for base rate, 1+ for volume tiers, or null if not tiered>,
  "tier_conditions": <structured condition object or null>,
  "conditions": <object with footnotes, caps, exclusions, etc. or null>,
  "section_ref": "<section name/number in source document>",
  "notes": "<any qualifiers or footnotes>"
}}

TIER CONDITIONS FORMAT (when tier_conditions is not null):
{{
  "logic": "AND" | "OR",
  "criteria": [
    {{
      "metric": "ADAV" | "ADRV" | "ADV" | "NBBO_PCT" | "TOTAL_VOLUME" | "CCV_PCT" | "CROSS_ASSET",
      "capacities": ["CUSTOMER", "MARKET_MAKER"],
      "security_filter": "PENNY" | null,
      "operator": ">=" | "<=" | ">" | "<",
      "value": 0.0050,
      "unit": "PCT_OCV" | "PCT_CCV" | "PCT_TCV" | "CONTRACTS" | "PERCENT",
      "description": "Human-readable description of this criterion"
    }}
  ]
}}

RULES:
- Rebates: negative amounts, is_rebate=true. Fees: positive amounts, is_rebate=false.
- All per-contract amounts in USD per contract.
- Participant mapping: "Public Customer"/"Priority Customer"/"Retail" → CUSTOMER; "Professional"/"Professional Customer" → PROFESSIONAL; "Market Maker"/"Specialist"/"LMM"/"DPM"/"PMM"/"CMM" → MARKET_MAKER; "Away Market Maker"/"Non-Member MM"/"FarMM" → AWAY_MARKET_MAKER; "Firm"/"Proprietary" → FIRM; "Broker-Dealer"/"BD"/"JBO" → BROKER_DEALER; grouped non-customer → NON_CUSTOMER
- When a fee depends on the contra-party (e.g., "Customer vs Non-Customer"), set contra_party_type.
- Include ALL volume tiers — each tier is a separate fee entry with the same fee_code but different tier_number and tier_conditions.
- Base/default rates have tier_number=0 and tier_conditions=null.
- For tiered entries, tier_group links related tiers (e.g., all "Customer Penny Add" tiers share tier_group="customer_penny_add").
- Extract EVERY fee mentioned including ORF, routing, surcharges, etc.
- Focus on OPTIONS transaction fees. Skip market data, connectivity, and membership fees unless they are per-contract.

{exchange_hints}

Return JSON:
{{
  "exchange_name": "<name>",
  "effective_date": "<date or null>",
  "fees": [<array of fee objects>],
  "extraction_notes": "<notes about extraction>"
}}"""
```

**Step 2: Update `extract()` to inject exchange hints**

In the `extract()` method, look up the exchange family and inject hints:

```python
from exnot.parser.extraction_hints import get_hints_for_exchange

def extract(self, document: ExtractedDocument, exchange_code: str) -> ExtractionResult:
    """Run the extraction pipeline."""
    result = ExtractionResult()

    logger.info(f"[{exchange_code}] Extracting fee data...")
    context = self._build_document_context(document)

    # Get exchange-family-specific hints
    hints = get_hints_for_exchange(exchange_code)
    exchange_hints = hints.get("prompt_addition", "")

    prompt = FEE_EXTRACTION_PROMPT.replace("{exchange_hints}", exchange_hints)

    text, stop_reason, in_tok, out_tok = self._call_api(
        [{"role": "user", "content": f"{prompt}\n\n{context}"}],
        max_tokens=8192,
    )
    # ... rest unchanged
```

**Step 3: Commit**

```bash
git add src/exnot/parser/ai_extractor.py
git commit -m "feat: V2 AI extraction prompt with expanded schema and exchange-family hints"
```

---

## Task 7: Rewrite Normalization Engine for V2

**Files:**
- Modify: `src/exnot/normalizer/engine.py` (simplify — AI now outputs canonical values)
- Test: `tests/unit/test_normalizer.py`

**Step 1: Write test for V2 normalization with tiers and contra-parties**

Add to `tests/unit/test_normalizer.py`:

```python
def test_v2_normalize_with_tiers(self):
    """Test V2 normalization with tier groups."""
    extraction = ExtractionResult(
        raw_fees=[
            {
                "fee_code": "PY",
                "participant_type": "CUSTOMER",
                "contra_party_type": None,
                "security_class": "PENNY",
                "order_type": "SIMPLE",
                "fee_type": "MAKER",
                "fee_unit": "PER_CONTRACT",
                "amount": -0.25,
                "is_rebate": True,
                "tier_group": "customer_penny_add",
                "tier_number": 0,
                "section_ref": "Transaction Fees",
            },
            {
                "fee_code": "PY",
                "participant_type": "CUSTOMER",
                "contra_party_type": None,
                "security_class": "PENNY",
                "order_type": "SIMPLE",
                "fee_type": "MAKER",
                "fee_unit": "PER_CONTRACT",
                "amount": -0.47,
                "is_rebate": True,
                "tier_group": "customer_penny_add",
                "tier_number": 2,
                "tier_conditions": {
                    "logic": "OR",
                    "criteria": [
                        {"metric": "ADV", "operator": ">=", "value": 0.01,
                         "unit": "PCT_OCV", "description": "ADV >= 1.00% OCV"}
                    ]
                },
                "section_ref": "Transaction Fees, Footnote 1",
            },
            {
                "fee_code": "ZA",
                "participant_type": "CUSTOMER",
                "contra_party_type": "NON_CUSTOMER",
                "security_class": "PENNY",
                "order_type": "COMPLEX",
                "fee_type": "MAKER",
                "fee_unit": "PER_CONTRACT",
                "amount": -0.40,
                "is_rebate": True,
                "conditions": {"footnotes": ["10"]},
                "section_ref": "Complex Orders",
            },
        ],
        exchange_name="Cboe BZX",
        confidence=0.95,
    )

    schedule = self.engine.normalize(extraction, "CBOE_BZX")

    assert len(schedule.fees) == 3
    # Base tier
    assert schedule.fees[0].fee_code == "PY"
    assert schedule.fees[0].tier_number == 0
    assert schedule.fees[0].tier_conditions is None
    # Volume tier
    assert schedule.fees[1].tier_number == 2
    assert schedule.fees[1].tier_conditions is not None
    assert schedule.fees[1].tier_conditions.logic == "OR"
    # Contra-party
    assert schedule.fees[2].contra_party_type == ParticipantType.NON_CUSTOMER
    assert schedule.fees[2].fee_code == "ZA"

def test_v2_normalize_contra_party(self):
    """Test V2 normalization preserves contra-party type."""
    extraction = ExtractionResult(
        raw_fees=[
            {
                "participant_type": "CUSTOMER",
                "contra_party_type": "CUSTOMER",
                "security_class": "PENNY",
                "order_type": "COMPLEX",
                "fee_type": "MAKER",
                "amount": 0.00,
                "is_rebate": False,
                "notes": "Customer vs Customer, free",
            },
        ],
        confidence=0.9,
    )

    schedule = self.engine.normalize(extraction, "TEST")
    assert len(schedule.fees) == 1
    assert schedule.fees[0].contra_party_type == ParticipantType.CUSTOMER
```

**Step 2: Run tests to verify they fail**

```bash
cd /home/yogidigital/projects/exnot && python -m pytest tests/unit/test_normalizer.py -v
```

**Step 3: Rewrite `src/exnot/normalizer/engine.py`**

The engine needs to handle both V1 (text-based types needing mapping) and V2 (canonical enum values) input. Keep the existing mappings as fallback, but try direct enum match first. Add handling for new fields.

Key changes to `_normalize_entry()`:
- Accept and pass through: `fee_code`, `contra_party_type`, `symbol`, `fee_unit`, `routing_destination`, `tier_group`, `tier_number`, `tier_conditions`, `conditions`, `section_ref`, `expiry_date`
- Keep existing fuzzy mappings as fallback for backward compatibility
- Parse `tier_conditions` dict into `TierCondition` Pydantic model

**Step 4: Run all normalizer tests**

```bash
cd /home/yogidigital/projects/exnot && python -m pytest tests/unit/test_normalizer.py -v
```

Expected: ALL PASS

**Step 5: Commit**

```bash
git add src/exnot/normalizer/engine.py tests/unit/test_normalizer.py
git commit -m "feat: V2 normalization engine with tier conditions, contra-party, fee codes"
```

---

## Task 8: Update Change Detector for V2 Dimensions

**Files:**
- Modify: `src/exnot/differ/detector.py`
- Test: `tests/unit/test_change_detector.py`

**Step 1: Update `_fee_key()` to include V2 dimensions**

The fee comparison key must now include `fee_code`, `contra_party_type`, `symbol`, and `tier_number` to correctly match fees across snapshots.

```python
def _fee_key(fee: NormalizedFeeEntry) -> tuple:
    """Create a comparison key for a fee entry."""
    return (
        fee.fee_code or "",
        fee.participant_type,
        fee.contra_party_type or "",
        fee.security_class,
        fee.symbol or "",
        fee.order_type,
        fee.fee_type,
        fee.tier_number if fee.tier_number is not None else -1,
    )
```

**Step 2: Update `FeeChangeEntry` dataclass to include V2 fields**

```python
@dataclass
class FeeChangeEntry:
    """A single detected fee change."""
    change_type: str  # NEW, MODIFIED, REMOVED
    fee_code: str | None = None
    participant_type: str | None = None
    contra_party_type: str | None = None
    security_class: str | None = None
    symbol: str | None = None
    order_type: str | None = None
    fee_type: str | None = None
    tier_number: int | None = None
    old_amount_cents: int | None = None
    new_amount_cents: int | None = None
    volume_tier: str | None = None
    description: str = ""
```

**Step 3: Update existing tests and add V2 test**

Update `tests/unit/test_change_detector.py` to include a test for detecting contra-party fee changes and tier changes.

**Step 4: Run tests**

```bash
cd /home/yogidigital/projects/exnot && python -m pytest tests/unit/test_change_detector.py -v
```

**Step 5: Commit**

```bash
git add src/exnot/differ/detector.py tests/unit/test_change_detector.py
git commit -m "feat: V2 change detector with fee_code, contra_party, symbol, tier matching"
```

---

## Task 9: Update Pipeline to Save V2 Data

**Files:**
- Modify: `src/exnot/workers/pipelines.py:270-299` (`_save_normalized_fees` function)

**Step 1: Update `_save_normalized_fees` to save V2 fields**

```python
def _save_normalized_fees(
    exchange: Exchange,
    snapshot: FeeScheduleSnapshot,
    schedule: NormalizedFeeSchedule,
    session: Session,
) -> list[NormalizedFee]:
    """Persist NormalizedFee ORM records to the database."""
    # First, create FeeTier records for any tier groups
    tier_map = _create_fee_tiers(exchange, snapshot, schedule, session)

    db_fees = []
    for entry in schedule.fees:
        # Look up tier_id if this entry belongs to a tier group
        tier_id = None
        if entry.tier_group and entry.tier_number is not None and entry.tier_number > 0:
            tier_key = (entry.tier_group, entry.tier_number)
            tier_id = tier_map.get(tier_key)

        fee = NormalizedFee(
            snapshot_id=snapshot.id,
            exchange_id=exchange.id,
            fee_code=entry.fee_code,
            participant_type=entry.participant_type.value,
            contra_party_type=entry.contra_party_type.value if entry.contra_party_type else None,
            security_class=entry.security_class.value,
            symbol=entry.symbol,
            order_type=entry.order_type.value,
            fee_type=entry.fee_type.value,
            fee_unit=entry.fee_unit.value if hasattr(entry, 'fee_unit') else "PER_CONTRACT",
            amount_cents=entry.amount_cents,
            is_rebate=entry.is_rebate,
            tier_id=tier_id,
            routing_destination=entry.routing_destination,
            conditions=entry.conditions,
            effective_date=entry.effective_date,
            expiry_date=getattr(entry, 'expiry_date', None),
            section_ref=getattr(entry, 'section_ref', None),
            notes=entry.notes,
            # Legacy fields
            volume_tier=entry.volume_tier,
            tier_threshold_pct=entry.tier_threshold_pct,
            tier_threshold_contracts=entry.tier_threshold_contracts,
        )
        db_fees.append(fee)

    session.add_all(db_fees)
    session.flush()
    logger.info(f"[{exchange.code}] Saved {len(db_fees)} normalized fee records")
    return db_fees
```

**Step 2: Add `_create_fee_tiers` helper function**

```python
def _create_fee_tiers(
    exchange: Exchange,
    snapshot: FeeScheduleSnapshot,
    schedule: NormalizedFeeSchedule,
    session: Session,
) -> dict[tuple[str, int], uuid.UUID]:
    """Create FeeTier records from fee entries and return mapping of (group, number) -> tier_id."""
    from exnot.db.models import FeeTier

    tier_map = {}
    seen = set()

    for entry in schedule.fees:
        if not entry.tier_group or entry.tier_number is None or entry.tier_number == 0:
            continue
        key = (entry.tier_group, entry.tier_number)
        if key in seen:
            continue
        seen.add(key)

        tier = FeeTier(
            snapshot_id=snapshot.id,
            exchange_id=exchange.id,
            tier_group=entry.tier_group,
            tier_number=entry.tier_number,
            tier_name=f"{entry.tier_group} Tier {entry.tier_number}",
            conditions=entry.tier_conditions.model_dump() if entry.tier_conditions else {},
            is_retroactive=True,
            notes=entry.notes,
        )
        session.add(tier)
        session.flush()
        tier_map[key] = tier.id

    if tier_map:
        logger.info(f"[{exchange.code}] Created {len(tier_map)} fee tier records")
    return tier_map
```

**Step 3: Update `_save_fee_changes` to include V2 fields**

Update the function at line 319 to pass `fee_code`, `contra_party_type`, `symbol`, and `tier_number` from the change report entries.

**Step 4: Commit**

```bash
git add src/exnot/workers/pipelines.py
git commit -m "feat: pipeline saves V2 normalized fees with tiers, conditions, contra-party"
```

---

## Task 10: Update Conftest Fixtures for V2

**Files:**
- Modify: `tests/conftest.py`

**Step 1: Update sample fixtures to include V2 fields**

The existing `sample_fee_entry` and `sample_schedule` fixtures need to import the new enums (`FeeUnit`) and can optionally include V2 fields. Since all new fields have defaults, existing fixtures should still work. Add a new `sample_v2_schedule` fixture that demonstrates the full V2 schema.

**Step 2: Run full test suite**

```bash
cd /home/yogidigital/projects/exnot && python -m pytest tests/ -v
```

**Step 3: Commit**

```bash
git add tests/conftest.py
git commit -m "test: update conftest fixtures for V2 schema compatibility"
```

---

## Task 11: Rebuild Docker and Test End-to-End

**Step 1: Rebuild Docker**

```bash
docker compose build && docker compose up -d
```

**Step 2: Apply migration**

```bash
docker compose exec web alembic upgrade head
```

**Step 3: Trigger scrape for one exchange to test full pipeline**

```bash
docker compose exec web python -c "
from exnot.workers.tasks import scrape_and_process_exchange
result = scrape_and_process_exchange.delay('MEMX_OPTIONS')
print(f'Task: {result.id}')
"
```

**Step 4: Check worker logs for V2 extraction**

```bash
docker compose logs --tail=50 worker
```

Verify:
- AI extraction outputs V2 JSON schema (fee_code, contra_party_type, tier_conditions, etc.)
- Normalization succeeds with >0 fees
- Fee tier records created for tiered entries
- Change detection works

**Step 5: Check database for V2 data**

```bash
docker compose exec db psql -U exnot -c "
SELECT fee_code, participant_type, contra_party_type, security_class, symbol,
       order_type, fee_type, fee_unit, amount_cents, is_rebate, section_ref
FROM normalized_fees
WHERE exchange_id = (SELECT id FROM exchanges WHERE code='MEMX_OPTIONS')
ORDER BY participant_type, security_class, fee_type
LIMIT 20;
"
```

```bash
docker compose exec db psql -U exnot -c "SELECT * FROM fee_tiers LIMIT 10;"
```

**Step 6: Commit all remaining changes**

```bash
git add -A
git commit -m "feat: fee normalization V2 — full-fidelity schema with tiers, contra-party, conditions"
```

---

## Task 12: Test with Complex Exchange (CBOE BZX or NASDAQ ISE)

**Step 1: Trigger scrape for a complex exchange**

```bash
docker compose exec web python -c "
from exnot.workers.tasks import scrape_and_process_exchange
result = scrape_and_process_exchange.delay('CBOE_BZX')
print(f'Task: {result.id}')
"
```

**Step 2: Monitor and verify**

Check that the AI extracts:
- Fee codes (PY, PC, PM, ZA, ZB, etc.)
- Multiple volume tiers with conditions
- Contra-party-dependent complex order fees
- SPY-specific rates as symbol="SPY"
- Routing fees with destinations

**Step 3: Repeat for NASDAQ ISE**

```bash
docker compose exec web python -c "
from exnot.workers.tasks import scrape_and_process_exchange
result = scrape_and_process_exchange.delay('NASDAQ_ISE')
print(f'Task: {result.id}')
"
```

Verify ISE-specific features: MM Plus tiers, Priority Customer Complex tiers, PIM discounts.

**Step 4: Compare fee counts**

```bash
docker compose exec db psql -U exnot -c "
SELECT e.code, COUNT(nf.id) as fee_count,
       COUNT(DISTINCT nf.fee_code) as unique_codes,
       COUNT(DISTINCT nf.tier_id) as tier_count
FROM normalized_fees nf
JOIN exchanges e ON e.id = nf.exchange_id
GROUP BY e.code
ORDER BY fee_count DESC;
"
```

Expected: CBOE_BZX should have 50-100+ entries, NASDAQ_ISE 80-200+, MEMX ~12-20.
