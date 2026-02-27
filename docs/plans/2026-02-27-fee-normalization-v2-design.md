# Fee Schedule Normalization V2 - Design Document

## Problem

The current normalization model (`NormalizedFee`) captures only 4 dimensions per fee entry:
`participant_type`, `security_class`, `order_type`, `fee_type`, plus a free-text `volume_tier`.

Real exchange fee schedules have 8-15 dimensions per entry including contra-party dependencies,
exchange-specific billing codes, multi-condition volume tiers, symbol-specific pricing,
routing destinations, premium-based surcharges, and stacking rebate logic.

Analysis of CBOE BZX (35+ fee codes, 7 tiers for one rebate), NASDAQ ISE (10 complex tiers,
MM Plus NBBO tiers, contra-party grids, linked symbol rebates), and MEMX (composite fee codes,
simple structure) shows that exchanges range from ~12 to 200+ distinct fee entries with wildly
different structural complexity.

## Goals

1. **Change detection**: Detect when ANY fee amount changes between snapshots
2. **Full fee lookup**: Query exact fees for specific scenarios (participant + security + order type + tier)
3. **Cross-exchange comparison**: Compare equivalent fees across all 18 exchanges on common dimensions

## Design

### Approach: Structured JSONB + Relational Core

Relational columns for dimensions common to ALL exchanges (enables cross-exchange queries).
JSONB `conditions` column for exchange-specific complexity (handles any exchange without schema changes).
Separate `FeeTier` table for volume-tiered pricing with structured condition logic.

---

### 1. Expanded Enums

#### ParticipantType
```
CUSTOMER              # Priority Customer / Public Customer / Retail
PROFESSIONAL          # Professional Customer
MARKET_MAKER          # Registered MM / Specialist / LMM / DPM / PMM / CMM
AWAY_MARKET_MAKER     # Non-ISE MM / FarMM / Remote MM
FIRM                  # Firm Proprietary / Non-Customer / OCC clearing member
BROKER_DEALER         # BD / JBO (Joint Back Office)
NON_CUSTOMER          # Catch-all grouping (some exchanges lump Firm+BD+AMM)
ALL                   # Applies to all participants (e.g., ORF)
```

#### SecurityClass
```
PENNY                 # Penny Pilot / Select Symbols
NON_PENNY             # Non-Penny / Non-Select
INDEX                 # Generic index options
EQUITY                # Equity options generally
SPY                   # SPY-specific rates (CBOE, ISE)
QQQ                   # QQQ-specific (ISE linked program)
IWM                   # IWM-specific (ISE linked program)
NDX                   # Nasdaq-100 Index
RUT                   # Russell 2000
VIX                   # VIX Index
ETF                   # ETF options
MINI                  # Mini options
ALL                   # Applies to all classes
```

#### OrderType
```
SIMPLE                # Regular / Standard single-leg
COMPLEX               # Multi-leg / Spread
AUCTION               # AIM / PRIME / Price Improvement auction
PIM                   # Price Improvement Mechanism (ISE/MIAX)
CROSSING              # Facilitation (FAC) / Solicitation (SOL)
DIRECTED              # Directed orders
QCC                   # Qualified Contingent Cross
FLEX                  # FLEX options
OPENING               # Opening/auction trades
ROUTED                # Orders routed to other exchanges
ALL                   # Applies to all order types
```

#### FeeType
```
MAKER                 # Add liquidity rebate/fee
TAKER                 # Remove liquidity fee
ROUTING               # Route-out fees
CROSSING_FEE          # Facilitation / crossing order fee
PIM_FEE               # PIM order fee
RESPONSE_FEE          # Responses to crossing/PIM/auction
BREAK_UP_REBATE       # FAC/SOL break-up rebate
SURCHARGE             # Index license surcharge, premium-based surcharge
ORF                   # Options Regulatory Fee
TRANSACTION           # Generic per-contract transaction fee
CLEARING              # Clearing/comparison fees
CONNECTIVITY          # Port fees, physical connections
MARKET_DATA           # Market data subscription fees
MEMBERSHIP            # Membership/access fees
CANCELLATION          # Order cancellation fees
STOCK_HANDLING        # Stock leg of stock-option orders
```

#### FeeUnit (NEW)
```
PER_CONTRACT          # Most transaction fees
PER_CONTRACT_SIDE     # ORF
PER_SHARE             # Stock handling fees
MONTHLY_FLAT          # Membership, connectivity, market data
PER_PORT_MONTHLY      # Port-based connectivity
PERCENTAGE            # % of notional or volume
PER_ORDER             # Cancellation fees
```

### 2. NormalizedFee Table (Revised)

```
NormalizedFee
├── id (UUID, PK)
├── snapshot_id (FK → FeeScheduleSnapshot)
├── exchange_id (FK → Exchange)
│
│  -- Core dimensions (relational, queryable) --
├── fee_code (String(20), nullable)         # Exchange billing code: "PY", "Dp1P", "ZA"
├── participant_type (Enum ParticipantType)  # WHO is charged
├── contra_party_type (Enum ParticipantType, nullable)  # WHO is on the other side
├── security_class (Enum SecurityClass)     # WHAT security class
├── symbol (String(20), nullable)           # Specific symbol if applicable (SPY, NDX, RUT)
├── order_type (Enum OrderType)             # HOW the order was submitted
├── fee_type (Enum FeeType)                 # WHAT kind of fee/rebate
├── fee_unit (Enum FeeUnit)                 # Unit of measurement
├── amount_cents (Integer)                  # Amount in hundredths of cent (USD). Negative = rebate
├── is_rebate (Boolean)
│
│  -- Tier linkage --
├── tier_id (FK → FeeTier, nullable)        # Link to tier if this is a tiered rate
│
│  -- Routing --
├── routing_destination (String(200), nullable)  # For ROUTED: target exchange(s) or groups
│
│  -- Conditions & metadata --
├── conditions (JSONB, nullable)            # Exchange-specific conditions (see schema below)
├── effective_date (Date, nullable)
├── expiry_date (Date, nullable)            # For time-limited rates
├── section_ref (String(50), nullable)      # Section reference in source document
├── notes (Text, nullable)                  # Human-readable notes
├── created_at (DateTime)
```

### 3. FeeTier Table (NEW)

Captures volume tier definitions with structured multi-condition logic.

```
FeeTier
├── id (UUID, PK)
├── snapshot_id (FK → FeeScheduleSnapshot)
├── exchange_id (FK → Exchange)
├── tier_group (String(100))                # Groups related tiers: "customer_penny_add"
├── tier_number (Integer)                   # Ordering within group: 1, 2, 3...
├── tier_name (String(200))                 # Display name: "Customer Penny Add Tier 3"
├── conditions (JSONB)                      # Structured tier conditions (see schema below)
├── is_retroactive (Boolean, default True)  # Whether tier applies retroactively
├── notes (Text, nullable)
├── created_at (DateTime)
```

### 4. JSONB Schemas

#### FeeTier.conditions
```json
{
  "logic": "AND",
  "criteria": [
    {
      "metric": "ADAV",
      "capacities": ["CUSTOMER"],
      "security_filter": "PENNY",
      "operator": ">=",
      "value": 0.0020,
      "unit": "PCT_OCV",
      "description": "Member ADAV in Simple Customer orders >= 0.20% of average OCV"
    },
    {
      "metric": "ADAV",
      "capacities": ["MARKET_MAKER"],
      "security_filter": null,
      "operator": ">=",
      "value": 0.0025,
      "unit": "PCT_OCV",
      "description": "Member ADAV in Simple Market Maker orders >= 0.25% of average OCV"
    }
  ]
}
```

Supported metric types:
- `ADAV` - Average Daily Added Volume
- `ADRV` - Average Daily Removed Volume
- `ADV` - Average Daily Volume (add + remove)
- `NBBO_PCT` - Percentage of time at NBBO
- `TOTAL_VOLUME` - Absolute monthly volume
- `CCV_PCT` - % of Customer Consolidated Volume
- `CROSS_ASSET` - Cross-asset volume condition

Supported unit types:
- `PCT_OCV` - % of OCC Customer Volume
- `PCT_CCV` - % of Customer Total Consolidated Volume
- `PCT_TCV` - % of Total Consolidated Volume
- `CONTRACTS` - Absolute contract count
- `PERCENT` - NBBO time percentage

#### NormalizedFee.conditions
```json
{
  "footnotes": ["5", "19"],
  "premium_condition": {
    "operator": ">=",
    "value": 25.00,
    "description": "Premium >= $25.00"
  },
  "cap": {
    "amount_cents": 500000,
    "unit": "PER_TRADE",
    "description": "Capped at $50 per trade"
  },
  "exclusions": ["FAC", "SOL", "PIM"],
  "linked_symbols": ["SPY", "QQQ"],
  "stacking_eligible": true,
  "cross_asset_condition": {
    "exchange": "BZX_EQUITIES",
    "metric": "ADAV",
    "threshold": 0.0045,
    "unit": "PCT_TCV"
  },
  "effective_range": {
    "from": "2026-01-02",
    "to": "2026-06-30"
  },
  "best_rate_rule": true,
  "raw_text": "Original footnote text preserved for audit"
}
```

### 5. Exchange-Family Extraction Prompts

Instead of one generic extraction prompt, use tailored prompts per exchange family
stored in `src/exnot/parser/extraction_hints.py`:

```python
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
            "RUT index license surcharges",
            "Complex order contra-party grids (Customer-vs-Customer, Customer-vs-NonCustomer)",
            "Cross-asset tiers (BZX Equities ADAV unlocks options rebates)",
            "Multi-condition AND/OR tier logic",
            "Opening trades often free",
            "Routing fees vary by destination exchange",
        ],
        "sections_to_extract": [
            "Transaction fees (simple maker/taker by participant + security class)",
            "Complex order fees (with contra-party dimension)",
            "Routing fees (by destination group)",
            "Volume tiers (all footnoted tiers with conditions)",
            "Index surcharges",
            "ORF",
            "Connectivity/port fees",
            "Market data fees",
        ],
    },
    "NASDAQ": {
        "families": ["NASDAQ_ISE", "NASDAQ_NOM", "NASDAQ_PHLX", "NASDAQ_GEMX",
                      "NASDAQ_MRX", "NASDAQ_NTX"],
        "terminology": {
            "Priority Customer": "Public Customer (< 390 orders/day)",
            "Professional Customer": "Professional (>= 390 orders/day)",
            "FarMM": "Non-Nasdaq ISE Market Maker / Away Market Maker",
        },
        "key_features": [
            "MM Plus tiers based on NBBO time % (not volume)",
            "Priority Customer Complex tiers (up to 10 levels)",
            "Linked symbol rebate programs (SPY-QQQ, SPY-IWM)",
            "PIM volume discounts (retroactive)",
            "Crossing/Solicitation rebate stacking",
            "QCC rebates with tier enhancements",
            "Select Symbols vs Non-Select Symbols (≈ Penny vs Non-Penny)",
            "Stock handling fees (per share, capped)",
            "60+ footnotes modifying base rates",
        ],
        "sections_to_extract": [
            "Regular order fees (Section 3: maker/taker by participant + security)",
            "MM Plus tiers (NBBO-based, symbol-specific groups)",
            "Complex order fees (Section 4: tiered Priority Customer rebates)",
            "Index options fees (Section 5: NDX, XND, BKX)",
            "Other fees (Section 6: QCC, Solicitation, PIM/FAC rebates, FLEX)",
            "Route-out fees",
            "ORF (with effective date ranges)",
            "Connectivity fees (ports, SQF volume discounts)",
            "Access/membership fees",
            "Market data fees",
        ],
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
            "Monthly volume calculation methodology",
            "Market Maker quoting obligation tiers",
        ],
        "sections_to_extract": [
            "Transaction fees (maker/taker by participant + security class)",
            "Complex order fees",
            "PRIME/cPRIME auction fees",
            "Volume tiers with conditions",
            "ORF",
            "Connectivity fees",
            "Market data fees",
            "Membership fees",
        ],
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
            "Sliding scale rebates",
        ],
        "sections_to_extract": [
            "Transaction fees (maker/taker per participant)",
            "Volume tiers (absolute ADV thresholds)",
            "Complex order fees",
            "Routing fees",
            "ORF",
            "Connectivity fees",
            "Market data fees",
        ],
    },
    "OTHER": {
        "families": ["BOX_OPTIONS", "MEMX_OPTIONS"],
        "key_features": [
            "BOX: PIP auction, simpler structure",
            "MEMX: Composite fee codes [Action][Capacity][Tier][SecurityClass]",
            "MEMX: Very few tiers, no contra-party dependency",
        ],
    },
}
```

### 6. AI Extraction Pipeline Changes

#### Updated extraction prompt structure

The AI extraction prompt will be split into two parts:
1. **Base prompt** - common JSON output schema (same for all exchanges)
2. **Exchange hints** - appended per-family guidance on what to look for

#### Updated output schema requested from AI

```json
{
  "exchange_name": "Cboe BZX Options",
  "effective_date": "2026-01-29",
  "fees": [
    {
      "fee_code": "PY",
      "participant_type": "CUSTOMER",
      "contra_party_type": null,
      "security_class": "PENNY",
      "symbol": null,
      "order_type": "SIMPLE",
      "fee_type": "MAKER",
      "fee_unit": "PER_CONTRACT",
      "amount": -0.25,
      "is_rebate": true,
      "routing_destination": null,
      "tier_group": "customer_penny_add",
      "tier_number": 0,
      "tier_conditions": null,
      "conditions": {},
      "section_ref": "Transaction Fees",
      "notes": "Base rate, no tier"
    },
    {
      "fee_code": "PY",
      "participant_type": "CUSTOMER",
      "contra_party_type": null,
      "security_class": "PENNY",
      "symbol": null,
      "order_type": "SIMPLE",
      "fee_type": "MAKER",
      "fee_unit": "PER_CONTRACT",
      "amount": -0.47,
      "is_rebate": true,
      "routing_destination": null,
      "tier_group": "customer_penny_add",
      "tier_number": 2,
      "tier_conditions": {
        "logic": "OR",
        "criteria": [
          {"metric": "ADV", "operator": ">=", "value": 0.01, "unit": "PCT_OCV",
           "description": "Member ADV in Simple orders >= 1.00% of average OCV"},
          {"metric": "ADAV", "capacities": ["CUSTOMER"], "operator": ">=",
           "value": 0.003, "unit": "PCT_OCV",
           "description": "Member ADAV in Simple Customer orders >= 0.30% of average OCV"}
        ]
      },
      "conditions": {"footnotes": ["1"]},
      "section_ref": "Transaction Fees, Footnote 1",
      "notes": "Tier 2"
    },
    {
      "fee_code": "ZA",
      "participant_type": "CUSTOMER",
      "contra_party_type": "NON_CUSTOMER",
      "security_class": "PENNY",
      "symbol": null,
      "order_type": "COMPLEX",
      "fee_type": "MAKER",
      "fee_unit": "PER_CONTRACT",
      "amount": -0.40,
      "is_rebate": true,
      "routing_destination": null,
      "tier_group": "complex_customer_penny",
      "tier_number": 0,
      "tier_conditions": null,
      "conditions": {"footnotes": ["10"]},
      "section_ref": "Complex Orders",
      "notes": "Customer contra Non-Customer, base rate"
    }
  ],
  "extraction_notes": "Extracted 87 fee entries across transaction, complex, routing, and regulatory sections."
}
```

### 7. Normalization Engine Changes

The normalization engine becomes simpler since AI now outputs structured data closer to the
final schema. Key changes:

1. **Direct enum mapping** - AI outputs canonical enum values directly (not free text)
2. **Tier creation** - Group fees by `tier_group`, create `FeeTier` records from `tier_conditions`
3. **Validation** - Check required fields present, amounts reasonable, enum values valid
4. **Deduplication** - Remove exact duplicate entries (same dimensions + amount)

### 8. Change Detection Updates

The differ needs to be updated to compare on the expanded dimensions:
- Match fees by: `(fee_code, participant_type, contra_party_type, security_class, symbol,
  order_type, fee_type, tier_number)`
- Detect: amount changes, new fees, removed fees, tier condition changes

### 9. Cross-Exchange Comparison

For comparing equivalent fees across exchanges:
```sql
-- Compare Customer PENNY MAKER fees across all exchanges (base tier only)
SELECT e.code, nf.amount_cents, nf.is_rebate, nf.fee_code
FROM normalized_fees nf
JOIN exchanges e ON e.id = nf.exchange_id
WHERE nf.participant_type = 'CUSTOMER'
  AND nf.security_class = 'PENNY'
  AND nf.fee_type = 'MAKER'
  AND nf.order_type = 'SIMPLE'
  AND nf.tier_id IS NULL  -- base tier only
  AND nf.snapshot_id IN (SELECT latest snapshot per exchange)
ORDER BY nf.amount_cents;
```

### 10. Migration Strategy

Since this changes the `NormalizedFee` table significantly:
1. Create new table `normalized_fees_v2` alongside existing
2. Create `fee_tiers` table
3. Add new enum values to existing enums
4. Migrate existing data (best-effort mapping)
5. Once verified, drop old table and rename

### 11. Files to Create/Modify

**New files:**
- `src/exnot/parser/extraction_hints.py` - Exchange family hints dict
- `src/exnot/normalizer/conditions.py` - JSONB condition validation (Pydantic models)
- Alembic migration for schema changes

**Modified files:**
- `src/exnot/db/models.py` - Expanded enums, revised NormalizedFee, new FeeTier
- `src/exnot/normalizer/schema.py` - Expanded Pydantic enums and NormalizedFeeEntry
- `src/exnot/normalizer/engine.py` - Simplified engine (AI outputs canonical values)
- `src/exnot/parser/ai_extractor.py` - Exchange-family-aware prompts, updated output schema
- `src/exnot/differ/detector.py` - Updated comparison logic for new dimensions
- `src/exnot/differ/comparator.py` - Cross-exchange comparison on expanded dimensions
