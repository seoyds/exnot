# Per-Exchange Extraction Prompts — Implementation Plan

> **For Claude:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task.

**Goal:** Replace the generic extraction prompt + family hints system with 18 standalone per-exchange extraction prompts, backed by an updated normalized schema with new dimensions (origin_code, exec_venue, product_type, etc.).

**Architecture:** A new `src/exnot/ai/prompts/` package holds a base prompt module and 18 exchange-specific prompt modules, each exporting a `PROMPT` string constant. A registry function `get_extraction_prompt(exchange_code)` assembles base + exchange prompt. The `ExtractedFee` Pydantic model gets new fields matching the design schema. The normalizer engine and DB model get corresponding updates. The section extractor agent's system instruction switches from generic `EXTRACTION_RULES` to per-exchange prompts.

**Tech Stack:** Python 3.12, Pydantic, PydanticAI, SQLAlchemy 2.x, Alembic, pytest

**Design doc:** `docs/plans/2026-03-03-per-exchange-extraction-prompts-design.md`

---

## Task 1: Update `ExtractedFee` model in `ai/types.py`

Add new fields to match the design schema. This is the AI output model — the LLM populates these fields.

**Files:**
- Modify: `src/exnot/ai/types.py:27-56`
- Test: `tests/unit/test_ai_types.py`

**Step 1: Write the failing test**

Add to `tests/unit/test_ai_types.py`:

```python
class TestExtractedFeeV3:
    """Tests for the new per-exchange schema fields."""

    def test_new_schema_fields(self):
        fee = ExtractedFee(
            fee_id="PY",
            fee_name="Customer Penny Maker",
            origin_code="CUSTOMER",
            contra_origin_code="ANY",
            product_type="SIMPLE",
            contra_product_type=None,
            listing_type="EQUITY",
            penny_class="PENNY",
            multi_listed=True,
            symbol="SPY",
            exec_venue="ELECTRONIC",
            liquidity_role="MAKER",
            auction_type=None,
            auction_role=None,
            fee_type="PER_CONTRACT",
            fee_value=-0.50,
            is_rebate=True,
            tier_level=0,
            tier_condition=None,
        )
        assert fee.origin_code == "CUSTOMER"
        assert fee.exec_venue == "ELECTRONIC"
        assert fee.fee_value == -0.50
        assert fee.fee_id == "PY"

    def test_minimal_fee_new_schema(self):
        """Minimal fee with only required new fields."""
        fee = ExtractedFee(
            fee_name="Test Fee",
            origin_code="MARKET_MAKER",
            product_type="SIMPLE",
            listing_type="EQUITY",
            penny_class="PENNY",
            exec_venue="ELECTRONIC",
            liquidity_role="TAKER",
            fee_type="PER_CONTRACT",
            fee_value=0.50,
            is_rebate=False,
        )
        assert fee.contra_origin_code is None
        assert fee.fee_id is None
        assert fee.tier_level is None

    def test_fee_value_validation(self):
        """fee_value exceeding $10/contract should fail for PER_CONTRACT."""
        with pytest.raises(ValidationError, match="exceeds"):
            ExtractedFee(
                fee_name="Bad Fee",
                origin_code="CUSTOMER",
                product_type="SIMPLE",
                listing_type="EQUITY",
                penny_class="PENNY",
                exec_venue="ELECTRONIC",
                liquidity_role="TAKER",
                fee_type="PER_CONTRACT",
                fee_value=15.00,
                is_rebate=False,
            )

    def test_backward_compat_old_fields(self):
        """Old-style fields should still work (backward compat during transition)."""
        fee = ExtractedFee(
            participant_type="CUSTOMER",
            security_class="PENNY",
            order_type="SIMPLE",
            fee_type="MAKER",
            amount=-0.50,
            is_rebate=True,
        )
        assert fee.participant_type == "CUSTOMER"
        assert fee.amount == -0.50
```

**Step 2: Run test to verify it fails**

Run: `pytest tests/unit/test_ai_types.py::TestExtractedFeeV3 -v`
Expected: FAIL — `ExtractedFee` doesn't have `origin_code`, `fee_value`, etc.

**Step 3: Write minimal implementation**

Update `ExtractedFee` in `src/exnot/ai/types.py`. Add the new fields as optional alongside old fields for backward compatibility during transition:

```python
class ExtractedFee(BaseModel):
    """Single fee entry extracted by AI.

    V3 fields (new schema — per-exchange prompts):
    """
    # --- V3 Identity ---
    fee_id: str | None = None
    fee_name: str | None = None

    # --- V3 Origin ---
    origin_code: str | None = None  # CUSTOMER | PROFESSIONAL | FIRM | BROKER_DEALER | MARKET_MAKER | AWAY_MARKET_MAKER
    contra_origin_code: str | None = None  # Same values + ANY, or null

    # --- V3 Product Dimensions ---
    product_type: str | None = None  # SIMPLE | COMPLEX
    contra_product_type: str | None = None
    listing_type: str | None = None  # EQUITY | ETF | INDEX
    penny_class: str | None = None  # PENNY | NON_PENNY
    multi_listed: bool | None = None
    symbol: str | None = None

    # --- V3 Execution Type (layered) ---
    exec_venue: str | None = None  # ELECTRONIC | FLOOR | ROUTED
    liquidity_role: str | None = None  # MAKER | TAKER | NONE
    auction_type: str | None = None  # AIM | PRIME | PIM | PIXL | QCC | etc.
    auction_role: str | None = None  # AGENCY | CONTRA | RESPONDER | INITIATOR

    # --- V3 Fee Value ---
    fee_value: float | None = None  # USD amount, negative = rebate
    is_rebate: bool = False

    # --- V3 Fee Unit ---
    fee_type: str | None = None  # PER_CONTRACT | PER_NOTIONAL | PER_SHARE | MONTHLY | PERCENTAGE (V3 meaning)

    # --- V3 Tiers ---
    tier_level: int | None = None  # 0 = base, 1+ = volume tier
    tier_condition: str | None = None  # Human-readable condition string

    # --- Legacy V2 fields (kept for backward compat during migration) ---
    fee_code: str | None = None
    participant_type: str | None = None
    contra_party_type: str | None = None
    security_class: str | None = None
    order_type: str | None = None
    # fee_type is shared (different semantics in V2 vs V3 — MAKER/TAKER vs PER_CONTRACT)
    fee_unit: str = "PER_CONTRACT"
    amount: float | None = None
    routing_destination: str | None = None
    tier_group: str | None = None
    tier_number: int | None = None
    tier_conditions: TierCondition | None = None
    conditions: dict | None = None
    section_ref: str | None = None
    notes: str | None = None

    @model_validator(mode="after")
    def validate_amount(self) -> "ExtractedFee":
        # V3 validation
        if self.fee_value is not None and self.fee_type == "PER_CONTRACT" and abs(self.fee_value) > 10.0:
            raise ValueError(
                f"Amount ${self.fee_value} exceeds $10/contract — likely an error. "
                f"If this is a flat/monthly fee, set fee_type to 'MONTHLY' or 'FLAT'."
            )
        # Legacy V2 validation
        if self.amount is not None and self.fee_unit == "PER_CONTRACT" and abs(self.amount) > 10.0:
            raise ValueError(
                f"Amount ${self.amount} exceeds $10/contract — likely an error. "
                f"If this is a flat/monthly fee, set fee_unit to 'MONTHLY' or 'FLAT'."
            )
        return self
```

**Step 4: Run test to verify it passes**

Run: `pytest tests/unit/test_ai_types.py -v`
Expected: ALL PASS (both old `TestExtractedFee` and new `TestExtractedFeeV3`)

**Step 5: Commit**

```bash
git add src/exnot/ai/types.py tests/unit/test_ai_types.py
git commit -m "feat: add V3 schema fields to ExtractedFee model"
```

---

## Task 2: Create prompt registry (`src/exnot/ai/prompts/`)

Create the base prompt module, exchange prompt modules, and the `get_extraction_prompt()` function.

**Files:**
- Create: `src/exnot/ai/prompts/__init__.py`
- Create: `src/exnot/ai/prompts/base.py`
- Create: `src/exnot/ai/prompts/registry.py`
- Create: 18 exchange modules (e.g., `cboe_bzx.py`, `nasdaq_ise.py`, etc.)
- Test: `tests/unit/test_prompt_registry.py`

**Step 1: Write the failing test**

Create `tests/unit/test_prompt_registry.py`:

```python
"""Tests for the per-exchange prompt registry."""

import pytest

from exnot.ai.prompts.registry import get_extraction_prompt, EXCHANGE_PROMPTS


class TestPromptRegistry:
    def test_get_prompt_for_known_exchange(self):
        prompt = get_extraction_prompt("CBOE_BZX")
        assert "EXCHANGE: Cboe BZX" in prompt
        assert "origin_code" in prompt  # Schema reference from base
        assert "TERMINOLOGY MAPPING" in prompt

    def test_get_prompt_for_all_exchanges(self):
        """Every exchange in the registry should return a non-empty prompt."""
        expected_exchanges = [
            "CBOE_BZX", "CBOE_EDGX", "CBOE_C1", "CBOE_C2",
            "NASDAQ_ISE", "NASDAQ_NOM", "NASDAQ_PHLX", "NASDAQ_GEMX",
            "NASDAQ_MRX", "NASDAQ_BX",
            "MIAX_OPTIONS", "MIAX_PEARL", "MIAX_EMERALD", "MIAX_SAPPHIRE",
            "NYSE_ARCA", "NYSE_AMERICAN",
            "BOX_OPTIONS", "MEMX_OPTIONS",
        ]
        for code in expected_exchanges:
            prompt = get_extraction_prompt(code)
            assert len(prompt) > 200, f"Prompt for {code} is too short"
            assert "EXCHANGE:" in prompt

    def test_unknown_exchange_raises(self):
        with pytest.raises(KeyError):
            get_extraction_prompt("UNKNOWN_EX")

    def test_prompt_contains_base(self):
        """Every prompt should include the base schema/rules."""
        prompt = get_extraction_prompt("CBOE_BZX")
        assert "origin_code" in prompt
        assert "fee_value" in prompt
        assert "REBATE" in prompt.upper() or "rebate" in prompt

    def test_prompt_count(self):
        assert len(EXCHANGE_PROMPTS) == 18
```

**Step 2: Run test to verify it fails**

Run: `pytest tests/unit/test_prompt_registry.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'exnot.ai.prompts'`

**Step 3: Write implementation**

Create the package and files. The base prompt defines the output schema and general rules. Each exchange module exports `PROMPT` containing that exchange's full prompt text from the design doc.

**`src/exnot/ai/prompts/__init__.py`:**
```python
"""Per-exchange extraction prompts."""
```

**`src/exnot/ai/prompts/base.py`:**
```python
"""Base prompt shared across all exchanges — defines output schema and general rules."""

BASE_PROMPT = """\
OUTPUT SCHEMA — extract every fee row with these fields:

IDENTITY:
- fee_id: Exchange fee code if exists (e.g., "PY", "DcP"), else null
- fee_name: Human-readable name (e.g., "Customer Penny Maker Tier 1")

ORIGIN / CONTRA ORIGIN:
- origin_code: CUSTOMER | PROFESSIONAL | FIRM | BROKER_DEALER | MARKET_MAKER | AWAY_MARKET_MAKER
- contra_origin_code: Same values + ANY, or null if not contra-dependent

OCC Capacity Code Reference:
- C = CUSTOMER (Customer, Priority Customer, Public Customer, Retail)
- P = PROFESSIONAL (Professional, Professional Customer)
- F = FIRM (Firm, Firm Proprietary)
- B = BROKER_DEALER (Broker-Dealer, Non-Member BD, JBO)
- M = MARKET_MAKER (Market Maker, LMM, RMM, Specialist, DOMM)
- O = AWAY_MARKET_MAKER (Away Market Maker, Non-[Exchange] Market Maker, FarMM)

PRODUCT DIMENSIONS:
- product_type: SIMPLE | COMPLEX
- contra_product_type: SIMPLE | COMPLEX | null
- listing_type: EQUITY | ETF | INDEX
- penny_class: PENNY | NON_PENNY
- multi_listed: true | false | null
- symbol: Specific symbol if fee is symbol-specific (SPY, VIX, etc.), else null

EXECUTION TYPE (layered):
- exec_venue: ELECTRONIC | FLOOR | ROUTED
- liquidity_role: MAKER | TAKER | NONE
- auction_type: null, AIM, PRIME, CPRIME, PIM, PIXL, CUBE, PIP, COPIP, SAM, FAC, SOL, QCC, CQCC, QFO, CQFO, BOLD, FLEX, OPENING, C2C, CC2C, CROSSING (or null for regular orders)
- auction_role: null, AGENCY, CONTRA, RESPONDER, INITIATOR

FEE VALUE:
- fee_type: PER_CONTRACT | PER_NOTIONAL | PER_SHARE | MONTHLY | PERCENTAGE
- fee_value: USD amount. Negative = rebate.
- is_rebate: true if rebate/credit

TIERS:
- tier_level: 0 = base/default, 1+ = volume/quality tier, null if no tiers
- tier_condition: Human-readable condition (e.g., "ADAV >= 0.35% of OCV"), null for base

RULES:
- Rebates: negative fee_value, is_rebate=true. Fees: positive fee_value, is_rebate=false.
- Amounts in parentheses like ($0.25) are REBATES → fee_value: -0.25, is_rebate: true
- All per-contract amounts in USD per contract.
- Include ALL volume tiers — each tier is a separate fee entry with different tier_level and tier_condition.
- Base/default rates have tier_level=0 and tier_condition=null.
- Extract EVERY fee mentioned including ORF, routing, surcharges.
- Focus on OPTIONS transaction fees. Skip market data, connectivity, and membership fees unless per-contract.
- If a REFERENCE CONTEXT section is provided, use it for interpretation but do NOT extract fees from it.
"""
```

**`src/exnot/ai/prompts/registry.py`:**
```python
"""Prompt registry — maps exchange codes to their extraction prompts."""

from exnot.ai.prompts.base import BASE_PROMPT
from exnot.ai.prompts.cboe_bzx import PROMPT as CBOE_BZX_PROMPT
from exnot.ai.prompts.cboe_edgx import PROMPT as CBOE_EDGX_PROMPT
from exnot.ai.prompts.cboe_c1 import PROMPT as CBOE_C1_PROMPT
from exnot.ai.prompts.cboe_c2 import PROMPT as CBOE_C2_PROMPT
from exnot.ai.prompts.nasdaq_ise import PROMPT as NASDAQ_ISE_PROMPT
from exnot.ai.prompts.nasdaq_nom import PROMPT as NASDAQ_NOM_PROMPT
from exnot.ai.prompts.nasdaq_phlx import PROMPT as NASDAQ_PHLX_PROMPT
from exnot.ai.prompts.nasdaq_gemx import PROMPT as NASDAQ_GEMX_PROMPT
from exnot.ai.prompts.nasdaq_mrx import PROMPT as NASDAQ_MRX_PROMPT
from exnot.ai.prompts.nasdaq_bx import PROMPT as NASDAQ_BX_PROMPT
from exnot.ai.prompts.miax_options import PROMPT as MIAX_OPTIONS_PROMPT
from exnot.ai.prompts.miax_pearl import PROMPT as MIAX_PEARL_PROMPT
from exnot.ai.prompts.miax_emerald import PROMPT as MIAX_EMERALD_PROMPT
from exnot.ai.prompts.miax_sapphire import PROMPT as MIAX_SAPPHIRE_PROMPT
from exnot.ai.prompts.nyse_arca import PROMPT as NYSE_ARCA_PROMPT
from exnot.ai.prompts.nyse_american import PROMPT as NYSE_AMERICAN_PROMPT
from exnot.ai.prompts.box_options import PROMPT as BOX_OPTIONS_PROMPT
from exnot.ai.prompts.memx_options import PROMPT as MEMX_OPTIONS_PROMPT


EXCHANGE_PROMPTS: dict[str, str] = {
    "CBOE_BZX": CBOE_BZX_PROMPT,
    "CBOE_EDGX": CBOE_EDGX_PROMPT,
    "CBOE_C1": CBOE_C1_PROMPT,
    "CBOE_C2": CBOE_C2_PROMPT,
    "NASDAQ_ISE": NASDAQ_ISE_PROMPT,
    "NASDAQ_NOM": NASDAQ_NOM_PROMPT,
    "NASDAQ_PHLX": NASDAQ_PHLX_PROMPT,
    "NASDAQ_GEMX": NASDAQ_GEMX_PROMPT,
    "NASDAQ_MRX": NASDAQ_MRX_PROMPT,
    "NASDAQ_BX": NASDAQ_BX_PROMPT,
    "MIAX_OPTIONS": MIAX_OPTIONS_PROMPT,
    "MIAX_PEARL": MIAX_PEARL_PROMPT,
    "MIAX_EMERALD": MIAX_EMERALD_PROMPT,
    "MIAX_SAPPHIRE": MIAX_SAPPHIRE_PROMPT,
    "NYSE_ARCA": NYSE_ARCA_PROMPT,
    "NYSE_AMERICAN": NYSE_AMERICAN_PROMPT,
    "BOX_OPTIONS": BOX_OPTIONS_PROMPT,
    "MEMX_OPTIONS": MEMX_OPTIONS_PROMPT,
}


def get_extraction_prompt(exchange_code: str) -> str:
    """Get the full extraction prompt for an exchange (base + exchange-specific).

    Args:
        exchange_code: Exchange code (e.g., "CBOE_BZX", "NASDAQ_ISE").

    Returns:
        Combined prompt string.

    Raises:
        KeyError: If exchange_code is not in the registry.
    """
    exchange_prompt = EXCHANGE_PROMPTS[exchange_code]
    return f"{BASE_PROMPT}\n\n{exchange_prompt}"
```

**Each exchange module** (e.g., `src/exnot/ai/prompts/cboe_bzx.py`):
```python
"""CBOE BZX extraction prompt."""

PROMPT = """\
EXCHANGE: Cboe BZX Options Exchange
FORMAT: HTML with fee code reference table
... (copy from design doc Section 3.1)
"""
```

Copy the prompt text for each exchange from the corresponding section (3.1–3.18) in the design doc. Each file is a single `PROMPT = """..."""` constant — no logic.

**Step 4: Run test to verify it passes**

Run: `pytest tests/unit/test_prompt_registry.py -v`
Expected: ALL PASS

**Step 5: Commit**

```bash
git add src/exnot/ai/prompts/ tests/unit/test_prompt_registry.py
git commit -m "feat: add per-exchange extraction prompt registry (18 exchanges)"
```

---

## Task 3: Wire prompts into `section_extractor.py` and `ai_extractor.py`

Replace the generic `EXTRACTION_RULES` + family hints with per-exchange prompts from the registry.

**Files:**
- Modify: `src/exnot/ai/agents/section_extractor.py:15-47`
- Modify: `src/exnot/parser/ai_extractor.py:78-181`
- Modify: `src/exnot/ai/deps.py:24` (rename `exchange_hints` → `exchange_prompt`)
- Test: `tests/unit/test_prompt_integration.py`

**Step 1: Write the failing test**

Create `tests/unit/test_prompt_integration.py`:

```python
"""Tests for prompt integration into extraction pipeline."""

from exnot.ai.deps import ExtractionDeps


class TestExtractionDepsPromptField:
    def test_exchange_prompt_field_exists(self):
        """ExtractionDeps should have exchange_prompt field."""
        deps = ExtractionDeps.__dataclass_fields__
        assert "exchange_prompt" in deps

    def test_exchange_prompt_default_empty(self):
        """exchange_prompt should default to empty string."""
        from unittest.mock import MagicMock
        deps = ExtractionDeps(
            model_registry=MagicMock(),
            cost_tracker=MagicMock(),
            exchange_code="TEST",
        )
        assert deps.exchange_prompt == ""
```

**Step 2: Run test to verify it fails**

Run: `pytest tests/unit/test_prompt_integration.py -v`
Expected: FAIL — `ExtractionDeps` has `exchange_hints`, not `exchange_prompt`

**Step 3: Write implementation**

**3a. Update `ExtractionDeps`** (`src/exnot/ai/deps.py`):
- Rename `exchange_hints: str = ""` → `exchange_prompt: str = ""`

**3b. Update `section_extractor.py`** (`src/exnot/ai/agents/section_extractor.py`):
- Remove the `EXTRACTION_RULES` constant
- Change the agent's `instructions` to a minimal preamble ("You are a financial data extraction specialist...")
- The per-exchange prompt is now injected via the user message by `ai_extractor.py`, not the system instruction

**3c. Update `ai_extractor.py`** (`src/exnot/parser/ai_extractor.py`):
- Replace `from exnot.parser.extraction_hints import get_hints_for_exchange` with `from exnot.ai.prompts.registry import get_extraction_prompt`
- Replace `hints = get_hints_for_exchange(exchange_code)` / `exchange_hints = hints.get("prompt_addition", "")` with `exchange_prompt = get_extraction_prompt(exchange_code)`
- Pass `exchange_prompt` (not `exchange_hints`) into `ExtractionDeps`
- In the prompt assembly loop, replace `if exchange_hints: prompt_parts.append(...)` with `prompt_parts.insert(0, exchange_prompt)` — the per-exchange prompt goes at the TOP of the user message, before the section data

**3d. Update `orchestrator.py`** — same rename: `ctx.deps.exchange_hints` → `ctx.deps.exchange_prompt` (2 occurrences at lines 195-196 and 309)

**Step 4: Run test to verify it passes**

Run: `pytest tests/unit/test_prompt_integration.py -v`
Expected: PASS

Run: `pytest tests/unit/ -v`
Expected: ALL PASS (verify nothing broke)

**Step 5: Commit**

```bash
git add src/exnot/ai/deps.py src/exnot/ai/agents/section_extractor.py \
  src/exnot/parser/ai_extractor.py src/exnot/ai/agents/orchestrator.py \
  tests/unit/test_prompt_integration.py
git commit -m "feat: wire per-exchange prompts into extraction pipeline"
```

---

## Task 4: Update normalizer schema enums

Add new enum values for the V3 schema dimensions (exec_venue, liquidity_role, etc.) alongside existing enums.

**Files:**
- Modify: `src/exnot/normalizer/schema.py`
- Test: `tests/unit/test_normalizer.py`

**Step 1: Write the failing test**

Add to `tests/unit/test_normalizer.py`:

```python
class TestV3SchemaEnums:
    def test_exec_venue_enum_exists(self):
        from exnot.normalizer.schema import ExecVenue
        assert ExecVenue.ELECTRONIC == "ELECTRONIC"
        assert ExecVenue.FLOOR == "FLOOR"
        assert ExecVenue.ROUTED == "ROUTED"

    def test_liquidity_role_enum_exists(self):
        from exnot.normalizer.schema import LiquidityRole
        assert LiquidityRole.MAKER == "MAKER"
        assert LiquidityRole.TAKER == "TAKER"
        assert LiquidityRole.NONE == "NONE"

    def test_product_type_enum_exists(self):
        from exnot.normalizer.schema import ProductType
        assert ProductType.SIMPLE == "SIMPLE"
        assert ProductType.COMPLEX == "COMPLEX"

    def test_listing_type_enum_exists(self):
        from exnot.normalizer.schema import ListingType
        assert ListingType.EQUITY == "EQUITY"
        assert ListingType.ETF == "ETF"
        assert ListingType.INDEX == "INDEX"

    def test_penny_class_enum_exists(self):
        from exnot.normalizer.schema import PennyClass
        assert PennyClass.PENNY == "PENNY"
        assert PennyClass.NON_PENNY == "NON_PENNY"

    def test_origin_code_enum_exists(self):
        from exnot.normalizer.schema import OriginCode
        assert OriginCode.CUSTOMER == "CUSTOMER"
        assert OriginCode.PROFESSIONAL == "PROFESSIONAL"
        assert OriginCode.FIRM == "FIRM"
        assert OriginCode.BROKER_DEALER == "BROKER_DEALER"
        assert OriginCode.MARKET_MAKER == "MARKET_MAKER"
        assert OriginCode.AWAY_MARKET_MAKER == "AWAY_MARKET_MAKER"
```

**Step 2: Run test to verify it fails**

Run: `pytest tests/unit/test_normalizer.py::TestV3SchemaEnums -v`
Expected: FAIL — `ImportError: cannot import name 'ExecVenue'`

**Step 3: Write implementation**

Add new enums to `src/exnot/normalizer/schema.py`:

```python
class OriginCode(str, Enum):
    CUSTOMER = "CUSTOMER"
    PROFESSIONAL = "PROFESSIONAL"
    FIRM = "FIRM"
    BROKER_DEALER = "BROKER_DEALER"
    MARKET_MAKER = "MARKET_MAKER"
    AWAY_MARKET_MAKER = "AWAY_MARKET_MAKER"
    ANY = "ANY"

class ProductType(str, Enum):
    SIMPLE = "SIMPLE"
    COMPLEX = "COMPLEX"

class ListingType(str, Enum):
    EQUITY = "EQUITY"
    ETF = "ETF"
    INDEX = "INDEX"

class PennyClass(str, Enum):
    PENNY = "PENNY"
    NON_PENNY = "NON_PENNY"

class ExecVenue(str, Enum):
    ELECTRONIC = "ELECTRONIC"
    FLOOR = "FLOOR"
    ROUTED = "ROUTED"

class LiquidityRole(str, Enum):
    MAKER = "MAKER"
    TAKER = "TAKER"
    NONE = "NONE"
```

**Step 4: Run test to verify it passes**

Run: `pytest tests/unit/test_normalizer.py -v`
Expected: ALL PASS

**Step 5: Commit**

```bash
git add src/exnot/normalizer/schema.py tests/unit/test_normalizer.py
git commit -m "feat: add V3 schema enums (OriginCode, ExecVenue, ProductType, etc.)"
```

---

## Task 5: Update normalizer engine to handle V3 fields

The normalizer maps raw AI output (dicts) to `NormalizedFeeEntry`. Update it to handle both V2 (old field names) and V3 (new field names) input.

**Files:**
- Modify: `src/exnot/normalizer/engine.py:206-264`
- Test: `tests/unit/test_normalizer.py`

**Step 1: Write the failing test**

Add to `tests/unit/test_normalizer.py`:

```python
class TestV3Normalization:
    def setup_method(self):
        self.engine = NormalizationEngine()

    def test_normalize_v3_fee(self):
        """V3-style raw fee dict should normalize correctly."""
        extraction = ExtractionResult(
            raw_fees=[
                {
                    "fee_id": "PY",
                    "fee_name": "Customer Penny Maker",
                    "origin_code": "CUSTOMER",
                    "contra_origin_code": None,
                    "product_type": "SIMPLE",
                    "listing_type": "EQUITY",
                    "penny_class": "PENNY",
                    "exec_venue": "ELECTRONIC",
                    "liquidity_role": "MAKER",
                    "auction_type": None,
                    "fee_type": "PER_CONTRACT",
                    "fee_value": -0.50,
                    "is_rebate": True,
                    "tier_level": 0,
                    "tier_condition": None,
                },
            ],
            confidence=0.95,
        )
        schedule = self.engine.normalize(extraction, "CBOE_BZX")
        assert len(schedule.fees) == 1
        fee = schedule.fees[0]
        assert fee.participant_type == ParticipantType.CUSTOMER
        assert fee.fee_type == FeeType.MAKER
        assert fee.is_rebate is True

    def test_normalize_v3_with_contra(self):
        extraction = ExtractionResult(
            raw_fees=[
                {
                    "fee_name": "Customer vs Non-Customer Complex Maker",
                    "origin_code": "CUSTOMER",
                    "contra_origin_code": "ANY",
                    "product_type": "COMPLEX",
                    "listing_type": "EQUITY",
                    "penny_class": "PENNY",
                    "exec_venue": "ELECTRONIC",
                    "liquidity_role": "MAKER",
                    "fee_type": "PER_CONTRACT",
                    "fee_value": -0.40,
                    "is_rebate": True,
                },
            ],
            confidence=0.9,
        )
        schedule = self.engine.normalize(extraction, "CBOE_BZX")
        assert schedule.fees[0].contra_party_type == ParticipantType.NON_CUSTOMER
        assert schedule.fees[0].order_type == OrderType.COMPLEX
```

**Step 2: Run test to verify it fails**

Run: `pytest tests/unit/test_normalizer.py::TestV3Normalization -v`
Expected: FAIL — normalizer doesn't recognize `origin_code`, `liquidity_role`, etc.

**Step 3: Write implementation**

In `NormalizationEngine._normalize_entry()`, detect V3 format (presence of `origin_code` key) and map:
- `origin_code` → `participant_type` (direct mapping: CUSTOMER→CUSTOMER, etc.)
- `contra_origin_code: ANY` → `contra_party_type: NON_CUSTOMER`
- `liquidity_role: MAKER/TAKER` → `fee_type: MAKER/TAKER`
- `product_type: COMPLEX` → `order_type: COMPLEX`; `SIMPLE` → `order_type: SIMPLE`
- `auction_type` (if set) → `order_type` mapped to existing enum (AIM→AUCTION, PRIME→PIM, QCC→QCC, etc.)
- `penny_class: PENNY/NON_PENNY` → `security_class: PENNY/NON_PENNY`
- `listing_type: INDEX` → `security_class: INDEX`; listing_type + penny_class together determine security_class
- `fee_value` → `amount`
- `fee_type` (V3: PER_CONTRACT) → `fee_unit` (V2: PER_CONTRACT)
- `tier_level` → `tier_number`
- `tier_condition` → stored in `notes` or conditions

If `origin_code` is NOT present, fall through to the existing V2 mapping path.

**Step 4: Run test to verify it passes**

Run: `pytest tests/unit/test_normalizer.py -v`
Expected: ALL PASS

**Step 5: Commit**

```bash
git add src/exnot/normalizer/engine.py tests/unit/test_normalizer.py
git commit -m "feat: normalizer handles V3 fee format from per-exchange prompts"
```

---

## Task 6: Add new columns to `NormalizedFee` DB model + Alembic migration

Add V3 dimension columns to the database model for future queries.

**Files:**
- Modify: `src/exnot/db/models.py` (NormalizedFee class)
- Create: Alembic migration via `alembic revision --autogenerate`

**Step 1: Update DB model**

Add these columns to `NormalizedFee` in `src/exnot/db/models.py`:

```python
# V3 dimensions (nullable for backward compat with existing data)
origin_code: Mapped[str | None] = mapped_column(String(30), nullable=True)
contra_origin_code: Mapped[str | None] = mapped_column(String(30), nullable=True)
product_type: Mapped[str | None] = mapped_column(String(20), nullable=True)
listing_type: Mapped[str | None] = mapped_column(String(20), nullable=True)
penny_class: Mapped[str | None] = mapped_column(String(20), nullable=True)
multi_listed: Mapped[bool | None] = mapped_column(Boolean, nullable=True)
exec_venue: Mapped[str | None] = mapped_column(String(20), nullable=True)
liquidity_role: Mapped[str | None] = mapped_column(String(20), nullable=True)
auction_type: Mapped[str | None] = mapped_column(String(30), nullable=True)
auction_role: Mapped[str | None] = mapped_column(String(20), nullable=True)
fee_name: Mapped[str | None] = mapped_column(String(500), nullable=True)
tier_level: Mapped[int | None] = mapped_column(Integer, nullable=True)
tier_condition_text: Mapped[str | None] = mapped_column(Text, nullable=True)
```

Using plain `String` columns (not `Enum`) for the V3 dimensions so we can add new values without migrations.

**Step 2: Generate migration**

Run: `alembic revision --autogenerate -m "add V3 fee dimensions to normalized_fees"`

**Step 3: Review the migration**

Read the generated migration file. Verify it adds the correct columns with `nullable=True`.

**Step 4: Run migration**

Run: `alembic upgrade head`
Expected: Migration applies successfully.

**Step 5: Commit**

```bash
git add src/exnot/db/models.py alembic/versions/*.py
git commit -m "feat: add V3 dimension columns to normalized_fees table"
```

---

## Task 7: Update `_save_normalized_fees` in pipelines.py

Persist the new V3 columns when saving normalized fees to the database.

**Files:**
- Modify: `src/exnot/workers/pipelines.py:649-673` (`_save_normalized_fees` function)
- Modify: `src/exnot/normalizer/schema.py` (add V3 fields to `NormalizedFeeEntry`)

**Step 1: Add V3 fields to `NormalizedFeeEntry`**

In `src/exnot/normalizer/schema.py`, add optional V3 fields:

```python
class NormalizedFeeEntry(BaseModel):
    # ... existing fields ...
    # V3 dimensions (stored to DB for querying)
    origin_code: str | None = None
    contra_origin_code: str | None = None
    product_type_v3: str | None = Field(None, alias="product_type_dim")
    listing_type: str | None = None
    penny_class: str | None = None
    multi_listed: bool | None = None
    exec_venue: str | None = None
    liquidity_role: str | None = None
    auction_type: str | None = None
    auction_role: str | None = None
    fee_name: str | None = None
    tier_level: int | None = None
    tier_condition_text: str | None = None
```

**Step 2: Populate V3 fields in normalizer**

In `NormalizationEngine._normalize_entry()`, when processing V3 input, also copy the raw values into the V3 fields on `NormalizedFeeEntry`.

**Step 3: Save V3 fields in `_save_normalized_fees`**

In `pipelines.py`, add the new fields to the `NormalizedFee(...)` constructor:

```python
fee = NormalizedFee(
    # ... existing fields ...
    origin_code=entry.origin_code,
    contra_origin_code=entry.contra_origin_code,
    product_type=entry.product_type_v3,
    listing_type=entry.listing_type,
    penny_class=entry.penny_class,
    multi_listed=entry.multi_listed,
    exec_venue=entry.exec_venue,
    liquidity_role=entry.liquidity_role,
    auction_type=entry.auction_type,
    auction_role=entry.auction_role,
    fee_name=entry.fee_name,
    tier_level=entry.tier_level,
    tier_condition_text=entry.tier_condition_text,
)
```

**Step 4: Run full test suite**

Run: `pytest tests/unit/ -v`
Expected: ALL PASS

**Step 5: Commit**

```bash
git add src/exnot/normalizer/schema.py src/exnot/workers/pipelines.py
git commit -m "feat: persist V3 fee dimensions to database"
```

---

## Task 8: Remove old `extraction_hints.py`

Now that per-exchange prompts replace the family hints, remove the old module.

**Files:**
- Delete: `src/exnot/parser/extraction_hints.py`
- Modify: Any remaining imports (search for `extraction_hints`)

**Step 1: Search for all imports**

Run: `grep -r "extraction_hints" src/`
Expected: Should only appear in `ai_extractor.py` (already updated in Task 3) and possibly `orchestrator.py`.

**Step 2: Remove the file and fix any remaining imports**

Delete `src/exnot/parser/extraction_hints.py`. Fix any remaining imports found in Step 1.

**Step 3: Run full test suite**

Run: `pytest tests/unit/ -v`
Expected: ALL PASS

**Step 4: Commit**

```bash
git rm src/exnot/parser/extraction_hints.py
git add -u
git commit -m "refactor: remove extraction_hints.py, replaced by per-exchange prompts"
```

---

## Task 9: Run linter and fix any issues

**Step 1: Run ruff**

Run: `ruff check src/exnot/ai/prompts/ src/exnot/ai/types.py src/exnot/ai/deps.py src/exnot/ai/agents/ src/exnot/parser/ai_extractor.py src/exnot/normalizer/ src/exnot/workers/pipelines.py src/exnot/db/models.py tests/unit/`

**Step 2: Fix any issues**

Run: `ruff format src/ tests/`

**Step 3: Verify tests still pass**

Run: `pytest tests/unit/ -v`

**Step 4: Commit**

```bash
git add -u
git commit -m "style: fix lint issues from per-exchange prompts implementation"
```

---

## Summary

| Task | What | Files Changed |
|------|------|---------------|
| 1 | Update `ExtractedFee` with V3 fields | `ai/types.py`, `test_ai_types.py` |
| 2 | Create prompt registry (18 exchanges) | `ai/prompts/` (21 files), `test_prompt_registry.py` |
| 3 | Wire prompts into extraction pipeline | `deps.py`, `section_extractor.py`, `ai_extractor.py`, `orchestrator.py` |
| 4 | Add normalizer schema enums | `normalizer/schema.py`, `test_normalizer.py` |
| 5 | Update normalizer engine for V3 | `normalizer/engine.py`, `test_normalizer.py` |
| 6 | DB migration for V3 columns | `db/models.py`, Alembic migration |
| 7 | Persist V3 to DB | `normalizer/schema.py`, `pipelines.py` |
| 8 | Remove old extraction_hints.py | Delete file, fix imports |
| 9 | Lint + format | All changed files |

**Total new files:** ~23 (21 in `ai/prompts/`, 2 test files)
**Total modified files:** ~8
**Total deleted files:** 1
