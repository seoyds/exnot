# Per-Exchange Extraction Prompts Design

**Date**: 2026-03-03
**Status**: Draft for review

## 1. Overview

Replace the current generic extraction prompt + family hints system with **18 standalone per-exchange extraction prompts**. Each prompt is self-contained with exchange-specific terminology mappings, table structure guidance, fee code patterns, tier handling, and auction mechanism instructions.

## 2. New Normalized Schema

Every extracted fee row maps to these fields:

### Identity
| Field | Type | Description |
|-------|------|-------------|
| `fee_id` | str/null | Exchange fee code if exists (`PY`, `DcP`, etc.), else null |
| `fee_name` | str | Human-readable name (e.g., "Customer Penny Maker Tier 1") |

### Origin / Contra Origin
| Field | Type | Values |
|-------|------|--------|
| `origin_code` | enum | `CUSTOMER`, `PROFESSIONAL`, `FIRM`, `BROKER_DEALER`, `MARKET_MAKER`, `AWAY_MARKET_MAKER` |
| `contra_origin_code` | enum/null | Same values + `ANY`, or null if not contra-dependent |

**OCC Capacity Code Reference** (for mapping exchange terminology):
| OCC Code | origin_code enum | Common exchange terms |
|----------|-----------------|----------------------|
| C | `CUSTOMER` | Customer, Priority Customer, Public Customer, Retail |
| P | `PROFESSIONAL` | Professional, Professional Customer, Non-Priority Customer, Public Customer (not Priority) |
| F | `FIRM` | Firm, Firm Proprietary |
| B | `BROKER_DEALER` | Broker-Dealer, Non-Member BD, JBO, Joint Back Office |
| M | `MARKET_MAKER` | Market Maker, LMM, RMM, PLMM, e-Specialist, Specialist, DOMM |
| O | `AWAY_MARKET_MAKER` | Away Market Maker, Non-[Exchange] Market Maker, FarMM |

### Product Dimensions
| Field | Type | Values |
|-------|------|--------|
| `product_type` | enum | `SIMPLE`, `COMPLEX` |
| `contra_product_type` | enum/null | `SIMPLE`, `COMPLEX`, null |
| `listing_type` | enum | `EQUITY`, `ETF`, `INDEX` |
| `penny_class` | enum | `PENNY`, `NON_PENNY` |
| `multi_listed` | bool/null | true, false, null |
| `symbol` | str/null | Specific symbol if fee is symbol-specific (SPY, VIX, etc.) |

### Execution Type (Layered)
| Field | Type | Values |
|-------|------|--------|
| `exec_venue` | enum | `ELECTRONIC`, `FLOOR`, `ROUTED` |
| `liquidity_role` | enum | `MAKER`, `TAKER`, `NONE` |
| `auction_type` | enum/null | null, `AIM`, `PRIME`, `CPRIME`, `PIM`, `PIXL`, `CUBE`, `PIP`, `COPIP`, `SAM`, `FAC`, `SOL`, `QCC`, `CQCC`, `QFO`, `CQFO`, `BOLD`, `FLEX`, `OPENING`, `C2C`, `CC2C`, `CROSSING` |
| `auction_role` | enum/null | null, `AGENCY`, `CONTRA`, `RESPONDER`, `INITIATOR` |

### Fee Value
| Field | Type | Description |
|-------|------|-------------|
| `fee_type` | enum | `PER_CONTRACT`, `PER_NOTIONAL`, `PER_SHARE`, `MONTHLY`, `PERCENTAGE` |
| `fee_value` | decimal | USD amount. Negative = rebate. |
| `is_rebate` | bool | true if rebate/credit |

### Tiers
| Field | Type | Description |
|-------|------|-------------|
| `tier_level` | int/null | 0 = base/default, 1+ = volume/quality tier |
| `tier_condition` | str/null | Human-readable condition (e.g., "ADAV >= 0.35% of OCV") |

---

## 3. Per-Exchange Prompts

Each prompt below is standalone. The system injects the prompt into the section extractor agent as the system instruction, along with the document content.

---

### 3.1 CBOE_BZX

```
EXCHANGE: Cboe BZX Options Exchange
FORMAT: HTML with fee code reference table

TERMINOLOGY MAPPING:
- "Customer" / "Priority Customer" → origin_code: CUSTOMER
- "Professional" → origin_code: PROFESSIONAL
- "Firm/BD/JBO" / "Firm" / "Broker Dealer" / "Joint Back Office" → origin_code: FIRM (for Firm), BROKER_DEALER (for Broker Dealer/JBO)
- "Market Maker" → origin_code: MARKET_MAKER
- "Away Market Maker" → origin_code: AWAY_MARKET_MAKER
- "Non-Customer" = any origin that is NOT CUSTOMER (i.e., PROFESSIONAL, FIRM, BROKER_DEALER, MARKET_MAKER, AWAY_MARKET_MAKER)

SECURITY CLASSES:
- "Penny Program Securities" → penny_class: PENNY, listing_type: EQUITY or ETF
- "Non-Penny Program Securities" → penny_class: NON_PENNY, listing_type: EQUITY or ETF
- RUT-specific fees → listing_type: INDEX, symbol: RUT
- SPY-specific rates within Penny → symbol: SPY

FEE CODES:
- BZX uses 2-character alphabetic fee codes with semantic prefixes:
  - P_ = Penny simple (PY, PA, PF, PM, PN, PC, PP)
  - N_ = Non-Penny simple (NY, NA, NF, NM, NN, NC, NP)
  - Z_ = Complex orders (ZA, ZB, ZC, ZD, ZE, ZF, ZG, ZH, ZJ, ZO, ZP)
  - R_ = Routed orders (RP, RQ, RR, RN, RO)
  - B_ = RUT on-exchange (BC, BM, BN, BO)
  - G_ = RUT routed (GC, GM, GN, GO)
  - O_ = Opening (OO, OC)
- Extract the fee_id from the Fee Code column or inline code references

TABLE STRUCTURE:
- Standard Rates Table: rows = participant types, columns = Penny Add | Penny Remove | Non-Penny Add | Non-Penny Remove
- "Add" = liquidity_role: MAKER (rebates shown in parentheses)
- "Remove" = liquidity_role: TAKER (fees shown as positive)
- Fee Codes Table: 3 columns — Fee Code | Description | Fee/(Rebate)
- Amounts in parentheses like ($0.25) are REBATES → fee_value: -0.25, is_rebate: true

COMPLEX ORDERS:
- Z-prefix codes. Complex orders distinguish by contra party:
  - ZA/ZB: origin_code: CUSTOMER, contra_origin_code: ANY (non-CUSTOMER)
  - ZC: origin_code: CUSTOMER, contra_origin_code: CUSTOMER (always free)
  - ZD/ZE/ZO/ZP: complex legs executing in Simple Book
  - ZF/ZG/ZH/ZJ: origin_code: non-CUSTOMER (no contra distinction)
- product_type: COMPLEX for all Z-prefix codes
- contra_product_type: null (both sides are complex)

TIERS:
- Volume tiers use ADAV/ADRV/ADV as percentage of OCV (OCC Customer Volume)
- Extract tier_level (0 for base, 1+ for tiered rates)
- Extract tier_condition as human-readable string (e.g., "ADAV >= 0.35% of OCV")
- CROSS-ASSET tiers combine BZX Options + BZX Equities volume — note in tier_condition

ROUTING:
- exec_venue: ROUTED for R-prefix codes
- Routing destination groups exist but extract as single fee entries per code
- liquidity_role: NONE for routed orders

OPENING:
- OO (simple) and OC (complex) are always $0.00
- auction_type: OPENING

RUT:
- listing_type: INDEX, symbol: RUT
- B-prefix = on-exchange, G-prefix = routed
- RUT has an Index License Surcharge of $0.45 on Non-Customer — extract as separate fee entry
- liquidity_role: NONE (flat fee, no maker/taker)

SPY:
- Within Market Maker Penny Add tiers (PM), SPY has its own column with different rebates
- Extract SPY-specific entries with symbol: SPY

SPECIAL RULES:
- All opening trades are free
- Customer-to-Customer complex trades (ZC) are always free
- Complex legs into Simple Book are free (ZD, ZE, ZO, ZP)
```

---

### 3.2 CBOE_EDGX

```
EXCHANGE: Cboe EDGX Options Exchange
FORMAT: HTML with fee code reference table

TERMINOLOGY MAPPING:
- "Customer" → origin_code: CUSTOMER
- "Professional" → origin_code: PROFESSIONAL
- "Market Maker" → origin_code: MARKET_MAKER
- "Away Market Maker" → origin_code: AWAY_MARKET_MAKER
- "Broker Dealer" → origin_code: BROKER_DEALER
- "Firm" → origin_code: FIRM
- "Joint Back Office" (JBO) → origin_code: BROKER_DEALER
- "Non-Customer" = PROFESSIONAL, FIRM, BROKER_DEALER, MARKET_MAKER, AWAY_MARKET_MAKER
- "Non-Customer, Non-Professional" = F, B, M, O

SECURITY CLASSES:
- "Penny Program Securities" → penny_class: PENNY
- "Non-Penny Program Securities" → penny_class: NON_PENNY
- listing_type: EQUITY or ETF (EDGX has no index products)

FEE CODES:
- 2-character codes with prefixes:
  - P_ = Penny simple, N_ = Non-Penny simple
  - Z_ = Complex, R_ = Routed, O_ = Opening
  - B_ = AIM mechanism, S_ = SAM mechanism, Q_ = QCC
  - CA = Customer contra Non-Customer adds liquidity
  - TP/TN = Customer-to-Customer adds liquidity
  - CC = AIM Customer-to-Customer Immediate Cross
  - E_ = Equity leg codes (firm-specific: EF, EL, EP, EQ, ES)

TABLE STRUCTURE:
- Standard Rates: participant rows × (Penny Add | Penny Remove | Non-Penny Add | Non-Penny Remove)
- "Add" = MAKER, "Remove" = TAKER
- Parenthetical amounts = rebates

COMPLEX ORDERS:
- Z-prefix codes with origin/contra grid:
  - When agency is Customer: ZC (CUSTOMER vs CUSTOMER = free), ZM/ZN (CUSTOMER vs MARKET_MAKER), ZT/ZR (CUSTOMER vs non-MM non-CUSTOMER)
  - When agency is Non-Customer contra Customer: ZA/ZB (rebates)
  - Add/Remove: ZF/ZH (add), ZG/ZJ (remove)
- product_type: COMPLEX, extract contra_origin_code from table context

AIM (Automated Improvement Mechanism):
- auction_type: AIM
- B-prefix codes: BA (Agency Non-Customer), BB (Contra Penny), BC (Agency Customer Penny), BD/BE (Response), BF (Contra Non-Penny), BG (Agency Customer Non-Penny)
- auction_role: AGENCY for BA/BC/BG, CONTRA for BB/BF, RESPONDER for BD/BE
- CC = AIM Customer-to-Customer Immediate Cross → free
- Break-up credits: extract as separate entries with is_rebate: true

SAM (Solicitation Auction Mechanism):
- auction_type: SAM
- S-prefix codes: SA-SH
- Same role structure as AIM

QCC:
- auction_type: QCC, Q-prefix codes (QA, QC, QM, QN, QO, QP)
- Customer and Professional: free
- Non-Customer Non-Professional: $0.20
- Volume rebate tiers based on absolute monthly contract volume

TIERS:
- Customer Simple: 6 tiers based on ADV % of OCV
- Customer Complex Penny: 5 tiers, Non-Penny: 4 tiers
- Market Maker: 5 tiers based on ADV % of OCV
- AIM Supplemental: 3 tiers based on "Interaction Rate"
- QCC Rebate: 3 tiers based on absolute monthly contracts

UNIQUE FEATURES:
- Customers receive rebates on BOTH sides (maker and taker)
- Marketing Fee codes (P, N, X) — extract if present
- AIM Interaction Rate tiers are unique to EDGX
- Break-up credits for both AIM and SAM
```

---

### 3.3 CBOE_C1

```
EXCHANGE: Cboe Options Exchange (C1)
FORMAT: CSV (3 columns: Fee Code | Description | Amount) — NO header row

TERMINOLOGY MAPPING:
- "Customer" → origin_code: CUSTOMER
- "Professional Customer" / "ProCustomer" → origin_code: PROFESSIONAL
- "Market-Maker" / "Market Maker" / "MarketMaker" → origin_code: MARKET_MAKER
- "Away Market-Maker" → origin_code: AWAY_MARKET_MAKER
- "Firm" → origin_code: FIRM
- "Broker-Dealer" → origin_code: BROKER_DEALER
- "Non-Customer, Non-Market-Maker, Non-Firm" → origin_code: BROKER_DEALER
- "Non-Customer, Non-Market-Maker, Non-Firm, Non-ProCustomer" → origin_code: BROKER_DEALER
- Note: hyphenation is inconsistent ("Market-Maker" vs "Market Maker")

SECURITY CLASSES — PRODUCT-SPECIFIC:
- "Penny" → penny_class: PENNY, listing_type: EQUITY/ETF
- "Non-Penny" → penny_class: NON_PENNY, listing_type: EQUITY/ETF
- "ETF" / "Equity" → listing_type: ETF or EQUITY, penny_class based on context
- "SPX" / "SPESG" → listing_type: INDEX, symbol: SPX, penny_class: NON_PENNY
- "VIX" → listing_type: INDEX, symbol: VIX, penny_class: NON_PENNY
- "RUT" / "MRUT" → listing_type: INDEX, symbol: RUT/MRUT
- "XSP" → listing_type: INDEX, symbol: XSP
- "OEX" / "XEO" → listing_type: INDEX, symbol: OEX/XEO
- "DJX" → listing_type: INDEX, symbol: DJX
- "MXEA" / "MXEF" → listing_type: INDEX, symbol: MXEA/MXEF
- "MGTN" → listing_type: INDEX, symbol: MGTN
- "NANOS" → listing_type: INDEX, symbol: NANOS
- "SPEQX" → listing_type: INDEX, symbol: SPEQX
- "CBTX" / "MBTX" → listing_type: INDEX, symbol: CBTX/MBTX
- "Sector Indexes" → listing_type: INDEX

FEE CODES:
- 123 unique 2-character codes. The fee_id IS the fee code.
- Description field is a comma-separated attribute string — decompose into schema fields
- Amount column: negative = rebate, positive = fee. Formats vary: 0.45, .45, 0, -0.30

PARSING THE DESCRIPTION FIELD:
- Split by comma. Each token maps to a schema field:
  - Participant type token → origin_code
  - "Penny"/"Non-Penny"/"ETF"/"Equity" → penny_class + listing_type
  - Product symbol (SPX, VIX, etc.) → symbol + listing_type: INDEX
  - "Adds liquidity"/"Adding Liquidity" → liquidity_role: MAKER
  - "Removes liquidity"/"Removing Liquidity" → liquidity_role: TAKER
  - "Manual" → exec_venue: FLOOR
  - "Electronic" → exec_venue: ELECTRONIC
  - "Contra Customer"/"Contra Non-Customer" → contra_origin_code
  - "Complex" → product_type: COMPLEX
  - "AIM Agency"/"AIM Responder"/"AIM Contra" → auction_type: AIM + auction_role
  - "QCC" → auction_type: QCC
  - "Routed" → exec_venue: ROUTED
  - "Terminal" → exec_venue: ROUTED (terminal-originated)
  - "Flex"/"Flex Micro" → note in fee_name
  - "Premium < $1.00" / "Premium >= $1.00" → tier_condition (premium-based tier)
  - ">= 100 contracts" / "< 100 contracts" → tier_condition (size-based tier)
  - ">= 10 contracts" / "< 10 contracts" → tier_condition
  - ">= 5000 Contracts" → tier_condition
  - "Facilitation" → auction_type: FAC
  - "Compression" / "Reversal" / "Strategy" → note in fee_name, fee_value typically 0

PREMIUM-BASED TIERS (unique to C1):
- SPX: 2 tiers — Premium < $1.00 vs >= $1.00
- VIX Simple: 4 tiers — $0.00-$0.10, $0.11-$0.99, $1.00-$1.99, >= $2.00
- VIX Complex: 4 tiers — same premium brackets, lower fees
- Extract as tier_level: 0-3, tier_condition: "Premium [range]"

CONTRA-PARTY PRICING:
- XSP and MGTN have contra-party-dependent fees
- "Contra Customer" → contra_origin_code: CUSTOMER
- "Contra Non-Customer" → contra_origin_code: ANY (meaning PROFESSIONAL/FIRM/BROKER_DEALER/MARKET_MAKER/AWAY_MARKET_MAKER)

EXECUTION VENUES:
- If "Electronic" in description → exec_venue: ELECTRONIC
- If "Manual" in description → exec_venue: FLOOR
- If "Routed" in description → exec_venue: ROUTED
- If none specified → exec_venue: ELECTRONIC (default for C1)

SPECIAL RULES:
- Facilitation (FF), Compression (SC, ST), Reversal (RV), Strategy (FS) are all $0.00
- Equity leg codes (EF, EL, EP, EQ, ES) are firm-specific — extract with fee_name noting the firm
- NANOS options have their own codes (NM, NN, NO)
- No volume-based tiers in the CSV — volume incentive programs are in supplementary documents
```

---

### 3.4 CBOE_C2

```
EXCHANGE: Cboe C2 Options Exchange
FORMAT: HTML with interactive sortable table

TERMINOLOGY MAPPING:
- "Public Customer" → origin_code: CUSTOMER
- "C2 Market-Maker" → origin_code: MARKET_MAKER
- "Non-Customer, Non-Market Maker" (includes Professional, Firm, BD, away MM, JBO) → origin_code: PROFESSIONAL
  NOTE: C2 only uses 3 participant buckets. Map "Non-Customer, Non-Market Maker" to PROFESSIONAL since it's the catch-all for non-CUSTOMER non-MARKET_MAKER.

SECURITY CLASSES:
- "Penny" → penny_class: PENNY, listing_type: EQUITY/ETF
- "Non-Penny" → penny_class: NON_PENNY, listing_type: EQUITY/ETF
- "Select Symbols" (SPY, AAPL, QQQ, IWM, SLV, AMC, AMD, AMZN, HYG, PLTR, TSLA, XLF) → separate table, penny_class: PENNY, listing_type: ETF/EQUITY
- "RUT" → listing_type: INDEX, symbol: RUT, penny_class: NON_PENNY
- "DJX" → listing_type: INDEX, symbol: DJX, penny_class: NON_PENNY

FEE CODES:
- 50+ 2-character codes with prefixes:
  - P_ = Penny simple, N_ = Non-Penny simple
  - Z_ = Complex (ZA-ZS)
  - S_ = Select Symbols (SC, SM, SM1, SL, SL2, SN)
  - B_ = RUT index (BC, BM, BN, BO)
  - D_ = DJX index (DC, DM, DN, DO)
  - R_ = Routed equity, F_ = Routed DJX, G_ = Routed RUT
  - O_ = Opening (OO, OC)
  - CA/CT = Resting simple vs resting complex interactions (free)

TABLE STRUCTURE:
- 4-column grid: Penny Add | Penny Remove | Non-Penny Add | Non-Penny Remove
- "Add" = MAKER, "Remove" = TAKER
- Separate tables for: Simple, Complex, Select Symbols, RUT, DJX, Routing
- Index products (RUT, DJX) use FLAT fees — no maker/taker split, liquidity_role: NONE

COMPLEX ORDERS:
- Z-prefix codes. NO contra-party grid (unlike BZX/EDGX)
- product_type: COMPLEX
- Separate Add/Remove for each participant in Penny and Non-Penny

SELECT SYMBOLS:
- Separate table with Add/Remove for CUSTOMER, MARKET_MAKER, non-CUSTOMER-non-MARKET_MAKER
- Market Maker has volume tiers (SM, SM1) and NBBO Joiner/Setter tiers (SL, SL2)

TIERS:
- MM Select Symbol Volume: 4 tiers based on ADAV as % of Average OCV
- NBBO Joiner/Setter: 2 tiers (same metric)
- tier_condition: "ADAV >= X% of Average OCV"

INDEX PRODUCTS:
- RUT: flat per-contract fees by participant, no maker/taker
- DJX: flat per-contract fees by participant, no maker/taker
- Both have Index License Surcharge on Non-Customer ($0.45 RUT, $0.12 DJX)
- Opening for both is free (BO, DO codes)

UNIQUE FEATURES:
- Only 3 participant categories (simplest of all exchanges)
- Resting-on-resting executions (CA, CT) are free
- No AIM/price improvement auctions
- Routing fee waiver for pre-positioned orders (entered prior business day or before 8:30 AM)
```

---

### 3.5 NASDAQ_ISE

```
EXCHANGE: Nasdaq ISE (International Securities Exchange)
FORMAT: HTML with multiple numbered sections

TERMINOLOGY MAPPING:
- "Priority Customer" → origin_code: CUSTOMER (not a broker/dealer AND <= 390 orders/day average)
- "Professional Customer" → origin_code: PROFESSIONAL (not a broker/dealer AND > 390 orders/day)
- "Market Maker" (ISE-registered) → origin_code: MARKET_MAKER
- "Non-Nasdaq ISE Market Maker" / "FarMM" → origin_code: AWAY_MARKET_MAKER
- "Firm Proprietary / Broker-Dealer" → origin_code: FIRM (for Firm), BROKER_DEALER (for Broker-Dealer)
  NOTE: ISE combines these in one row. Extract as origin_code: FIRM for the combined entry, or split if separate rates given.
- "Non-Priority Customers" = MARKET_MAKER, AWAY_MARKET_MAKER, FIRM, BROKER_DEALER, PROFESSIONAL

SECURITY CLASSES:
- "Select Symbols" = Penny Interval Program → penny_class: PENNY
- "Non-Select Symbols" = NOT in Penny Interval → penny_class: NON_PENNY
- NDX, XND, MNX → listing_type: INDEX, symbol as given
- All others → listing_type: EQUITY or ETF

TABLE STRUCTURE:
- Section 3 (Regular Orders): rows = participant types, columns = Maker Rebate/Fee | Taker Fee | Crossing Fee (ex PIM) | PIM Fee | Response to Crossing | Response to PIM | FAC/SOL Break-up Rebate | PIM Break-up Rebate
- Separate tables for Select Symbols and Non-Select Symbols
- Section 4 (Complex Orders): separate sub-tables for Priority Customer rebate tiers, maker/taker grid, crossing grid
- Section 5 (Index Options): simpler flat-fee tables
- Section 6 (Other): QCC, SOL, PIM/FAC, FLEX, Route-Out

MAKER/TAKER:
- "Maker Rebate/Fee" → liquidity_role: MAKER
- "Taker Fee" → liquidity_role: TAKER
- Priority Customer Select: Maker = $0.00, Taker = fee
- Priority Customer Non-Select: Maker = rebate, Taker = $0.00
- Rebates in parentheses

COMPLEX ORDERS (Section 4):
- product_type: COMPLEX
- Priority Customer Complex Rebate: 10 tiers based on % of Customer Total Consolidated Volume
- Maker/Taker grid has a "vs. Priority Customer" column — extract contra_origin_code: CUSTOMER
- $0.12 surcharge when Non-Priority takes vs Priority Customer in Complex Book

MARKET MAKER PLUS TIERS:
- Based on % time at NBBO (quoting quality, not volume)
- Different tier sets for: general Select, SPY/QQQ/IWM, AMZN/META/NVDA, Non-Select
- tier_condition: "NBBO time >= X%"
- Cross-symbol qualification: achieving tier in 2 of 3 linked symbols qualifies the third
- "Linked Maker Rebate" for SPY/QQQ/IWM Tier 2+ — extract as separate entries

AUCTION TYPES:
- FAC (Facilitation): auction_type: FAC
- SOL (Solicitation): auction_type: SOL
- PIM (Price Improvement Mechanism): auction_type: PIM
- QCC: auction_type: QCC
- FLEX: note in fee_name
- Block Order Mechanism: auction_type: CROSSING
- Exposure Auction: originating = MAKER rates, contra = TAKER rates

AUCTION ROLES:
- "Fee for Crossing Orders" → auction_role: AGENCY + CONTRA (both sides)
- "Fee for Responses to Crossing Orders" → auction_role: RESPONDER
- "Break-up Rebate" → separate entry with is_rebate: true

CONTRA-PARTY DEPENDENCIES (embedded in footnotes):
- Footnote (6): Non-Select Tier 3 changes from rebate to fee when contra is Priority Customer
- Footnote (3): Taker fee changes based on contra being Priority Customer
- Footnote (8): $0.12 surcharge on Non-Priority vs Priority Customer in Complex Book
- Extract these as separate fee entries with contra_origin_code: CUSTOMER

ROUTING:
- exec_venue: ROUTED
- Flat $0.60 Select / $1.20 Non-Select for all participants
- liquidity_role: NONE

SPECIAL RULES:
- NDX/XND/MNX excluded from complex order rebates
- Complex XND orders use Section 5 (Index) fees instead of Section 4
- Stock-option orders: $0.0010/share stock handling fee (capped $50/trade) → fee_type: PER_SHARE
- "Net zero" complex orders (within $0.01 debit/credit) excluded from rebates
```

---

### 3.6 NASDAQ_NOM

```
EXCHANGE: Nasdaq Options Market (NOM)
FORMAT: HTML with tiered tables and heavy footnotes

TERMINOLOGY MAPPING:
- "Customer" (C) → origin_code: CUSTOMER
- "Professional" (P) → origin_code: PROFESSIONAL
- "Broker-Dealer" (B) → origin_code: BROKER_DEALER
- "Firm" (F) → origin_code: FIRM
- "Non-NOM Market Maker" (O) → origin_code: AWAY_MARKET_MAKER
- "NOM Market Maker" (M) → origin_code: MARKET_MAKER
- "Joint Back Office" (J) → origin_code: BROKER_DEALER (same pricing as BD)

SECURITY CLASSES:
- "Penny Symbols" → penny_class: PENNY
- "Non-Penny Symbols" → penny_class: NON_PENNY
- SPY/QQQ/IWM enhanced rates → symbol: SPY/QQQ/IWM, penny_class: PENNY
- listing_type: EQUITY or ETF (NOM has no index products)

TABLE STRUCTURE:
- Add Liquidity (Penny): 6 rows (tiers) × 6 columns (participant types) — this is the primary table
- Add Liquidity (Non-Penny): flat table (one row per participant), NOM MM has 4 sub-tiers via footnote
- Remove Liquidity: flat table — rows = participants, columns = Penny | Non-Penny
- No fee codes — construct fee_id from context (e.g., "NOM-C-PENNY-ADD-T1")

MAKER/TAKER:
- "Rebates to Add Liquidity" → liquidity_role: MAKER, is_rebate: true
- "Fees to Remove Liquidity" → liquidity_role: TAKER, is_rebate: false
- Add side is tiered; Remove side is mostly flat

DUAL TIER SYSTEMS (independent numbering):
- Customer/Professional Add Penny: 6 tiers based on % Industry Customer Equity+ETF Option ADV
  - tier_level: 1-6
  - Some tiers have OR conditions (e.g., "Above 0.20% OR 0.05% + MARS")
- NOM Market Maker Add Penny: 6 tiers (different thresholds, some with composite AND/OR conditions)
  - tier_level: 1-6, tier_group must be different (e.g., "NOM_MM_ADD_PENNY")
- NOM MM Non-Penny Sub-Tiers (Footnote 5): 3 sub-tiers by ADV percentage

FOOTNOTE-BASED OVERRIDES (critical):
- Footnote 4: SPY/QQQ/IWM enhanced MM rebates → extract as symbol-specific entries
- Footnote 5: Non-Penny NOM MM sub-tiers → extract as separate tiered entries
- Footnote 7: High-volume Customer rebate enhancements (+$0.02 or +$0.05) → additional tier entries
- Footnote 9: 3.00%+ Consolidated Volume override pricing → separate tier group
- Footnote 10: Composite condition override pricing → separate tier group
- Footnote 12: Non-Penny add-on for Customer/Professional by tier
- These footnotes REPLACE normal tier pricing — model as separate tier groups

MARS PROGRAM:
- 9 tiers based on absolute ADV (contracts, not percentage)
- fee_type: PER_CONTRACT, exec_venue: ROUTED (subsidy for routing to NOM)
- tier_condition: "ADV >= X contracts"

COMPLEX ORDERS:
- NOM does NOT have separate complex order pricing
- All fees apply to both simple and complex → product_type: SIMPLE (or omit distinction)

OPENING:
- auction_type: OPENING
- Customer orders get Add Liquidity rebates (unless contra is also Customer)
- All others pay Remove Liquidity fees

ROUTING:
- exec_venue: ROUTED
- Flat fees per participant type

CROSS-ASSET CONDITIONS:
- Several tier qualifications reference Nasdaq equities activity (M-ELO ADV, MOC/LOC)
- Note in tier_condition: "CROSS_ASSET: [description]"
```

---

### 3.7 NASDAQ_PHLX

```
EXCHANGE: Nasdaq PHLX
FORMAT: HTML (text-formatted tables, NOT semantic HTML tables)

TERMINOLOGY MAPPING:
- "Customer" → origin_code: CUSTOMER
- "Professional" → origin_code: PROFESSIONAL
- "Lead Market Maker" / "Market Maker" (often grouped as "LMM/MM") → origin_code: MARKET_MAKER
- "Broker-Dealer" (includes JBO) → origin_code: BROKER_DEALER
- "Firm" → origin_code: FIRM
- "Directed Market Maker" → origin_code: MARKET_MAKER (sub-type, note in fee_name)
- "Non-Customer" = PROFESSIONAL, FIRM, BROKER_DEALER, MARKET_MAKER, AWAY_MARKET_MAKER

SECURITY CLASSES:
- "Penny Symbol" → penny_class: PENNY
- "Non-Penny Symbol" → penny_class: NON_PENNY
- SPY → ENTIRELY SEPARATE section (Section 3), symbol: SPY, penny_class: PENNY
- NDX/NDXP/EXGN/XND → listing_type: INDEX, symbol as given
- "Singly Listed" (Section 5.C) → multi_listed: false
- "FX Options" (Section 5.D) → listing_type: INDEX, note symbols

DUAL VENUE — ELECTRONIC vs FLOOR:
- Section 4 has BOTH Electronic and Floor rows for each participant × Penny/Non-Penny
- exec_venue: ELECTRONIC or FLOOR
- Monthly Market Maker Cap ($650,000) applies ONLY to electronic
- Monthly Firm Fee Cap ($250,000) applies ONLY to floor

TABLE STRUCTURE:
- Section 3 (SPY): Part A = Simple, Part B = Complex, Part C = PIXL
- Section 4 (Multiply Listed): rows = Electronic Penny | Electronic Non-Penny | Floor Penny | Floor Non-Penny
  columns = Customer | Professional | LMM/MM | Broker-Dealer | Firm
- Crossing Order tables: columns = Crossing Order Fee | Response Fee | Breakup Rebate
- Customer Rebate Program: 5 tiers × 4 categories (A/B = simple, C/D = complex penny/non-penny)

MAKER/TAKER:
- "Add Liquidity" → MAKER
- "Remove Liquidity" → TAKER
- SPY LMM/MM Add: 6-tier rebate schedule

COMPLEX ORDERS:
- product_type: COMPLEX
- Customer Rebate Categories C and D are complex-specific
- Footnote [2]: complex orders at different rate ($0.40)
- Surcharges [6],[7]: $0.12 for complex removing liquidity
- SPY Complex (Part B): entirely separate table from SPY Simple (Part A)
- Complex Order Surcharge: $0.15 for SPY customer complex vs MM/LMM simple quotes

AUCTION TYPES:
- PIXL (Price Improvement by Xchange): auction_type: PIXL
  - Initiating Order, PIXL Order, PIXL Response (during/prior auction)
  - Complex PIXL rebate for >499 contracts
  - SPY PIXL: separate rates in Section 3.C
- Crossing Orders (FAC/SOL): auction_type: FAC or SOL
  - Separate tables for simple penny, simple non-penny, complex
  - Columns: crossing fee | response fee | breakup rebate
- QCC: auction_type: QCC
  - $0.20 transaction fee, multi-tier rebate
- Order Exposure Alert: SPY-specific, auction_type: CROSSING

TIERS:
- Customer Rebate: 5 tiers based on % National Customer Volume
- SPY LMM/MM Add: 6 tiers based on % Total Cleared Customer Volume
- Floor Broker Incentive: 4 tiers based on absolute contract count
- QCC Rebate: 3 tiers
- MARS: 7 tiers based on ADV

XND INCENTIVE PROGRAM (3D MATRIX):
- listing_type: INDEX, symbol: XND
- 6 premium brackets × 3 expiration buckets × quoting width requirement
- Extract as individual entries with tier_condition describing the 3D position
- Premium ranges: $0-$1, $1.01-$3, $3.01-$5, $5.01-$10, $10.01-$25, >$25
- Expiration buckets: 14 days, 15-60 days, 61+ days
- Cumulative rebate up to $0.05 for heightened quoting standards

INDEX OPTIONS (Section 5):
- NDX/NDXP: Multiple stacking surcharges ($0.25 + $0.50 + $1.50 for non-customer)
- Extract surcharges as SEPARATE fee entries
- NDX premium surcharge: $0.25 for premium >= $25.00 → tier_condition

SPECIAL RULES:
- SPY excluded from Customer Rebate Program and Marketing Fees
- Broad-based index options excluded from Customer Rebate Program rebates (but volume counts)
- Floor Originated Strategy Executions: rebates for dividend, merger, reversal, etc.
- Conditional footnotes with stacking modifiers (*,#,&,**) — extract each as separate entry
- Multiple overlapping monthly caps
```

---

### 3.8 NASDAQ_GEMX

```
EXCHANGE: Nasdaq GEMX
FORMAT: HTML with tiered tables

TERMINOLOGY MAPPING:
- "Market Maker" → origin_code: MARKET_MAKER
- "Non-Nasdaq GEMX Market Maker (FarMM)" → origin_code: AWAY_MARKET_MAKER
- "Firm Proprietary / Broker-Dealer" → origin_code: FIRM (combined row)
- "Professional Customer" → origin_code: PROFESSIONAL
- "Priority Customer" → origin_code: CUSTOMER

SECURITY CLASSES:
- "Penny Symbols" → penny_class: PENNY
- "Non-Penny Symbols (Excluding Index Options)" → penny_class: NON_PENNY
- "Index Options" (NDX only) → listing_type: INDEX, symbol: NDX
- SPY/QQQ/IWM overrides (footnote 15) → symbol: SPY/QQQ/IWM

TABLE STRUCTURE:
- Table A (Penny): 5 participant rows × (Maker Rebate Tiers 1-4 | Taker Fee Tiers 1-4 | Crossing Fee | Response Fee)
- Table B (Non-Penny): identical structure
- Table C (Index): participant rows × single Fee column (flat, no tiers)

MAKER/TAKER:
- "Maker Rebate" → liquidity_role: MAKER
- "Taker Fee" → liquidity_role: TAKER
- Rebates in parentheses

4-TIER STRUCTURE:
- Based on Maker volume as % of Customer Total Consolidated Volume
- Tier 1: < 0.85%, Tier 2: 0.85-1.2%, Tier 3: 1.2-1.75%, Tier 4: >= 1.75%
- Only MM and Priority Customer get enhanced maker tiers (footnote 5)
- All participants get reduced taker tiers (footnote 3)
- FarMM/Firm/BD/Professional: only Tier 1 maker rebate (Tiers 2-4 show n/a)

COMPLEX ORDERS:
- GEMX has NO separate complex order pricing
- product_type: SIMPLE (all fees apply uniformly)

AUCTION TYPES:
- Crossing Orders (FAC, SOL, Block): auction_type: CROSSING
  - Flat fee $0.20 (non-PC) / $0.00 (PC)
- PIM: auction_type: PIM — $0.05 flat (footnotes 11-12)
- QCC: auction_type: QCC — excluded from MARS

CONTRA-PARTY DEPENDENCIES:
- Footnote 16: Non-Priority Taker = $1.10 vs Priority Customer; Priority Customer Taker = $0.85 vs Priority Customer → extract with contra_origin_code: CUSTOMER
- Footnote 18: MM/FarMM Tier 3-4 Penny Taker = $0.43 when self-trading or affiliated → note in tier_condition

NDX SURCHARGES (stack):
- Footnote 9: $0.25 base surcharge for Non-Priority
- Footnote 14: $0.25 premium surcharge (premium >= $25.00)
- Footnote 20: $1.50 surcharge for Non-Priority removing liquidity
- Extract EACH as a separate fee entry

MARS PROGRAM:
- 3 tiers based on ADV
- exec_venue: ROUTED (subsidy)
- Requires specific technology prerequisites

SPY/QQQ/IWM OVERRIDES (Footnote 15):
- MM Maker Rebate all tiers: ($0.38) — overrides normal tiered values
- Priority Customer Taker Tiers 1-2: $0.44 — overrides normal values
- Extract as symbol-specific entries
```

---

### 3.9 NASDAQ_MRX

```
EXCHANGE: Nasdaq MRX (Mercury)
FORMAT: HTML with tiered tables

*** CRITICAL: MRX USES AN INVERTED MAKER/TAKER MODEL ***
- Market Makers PAY MORE to MAKE (provide liquidity) than to TAKE
- Priority Customers receive REBATES as TAKERS
- This is the OPPOSITE of most exchanges

TERMINOLOGY MAPPING:
- "Market Maker" → origin_code: MARKET_MAKER
- "Non-Nasdaq MRX Market Maker (FarMM)" → origin_code: AWAY_MARKET_MAKER
- "Firm Proprietary/Broker-Dealer" → origin_code: FIRM (combined row)
- "Professional Customer" → origin_code: PROFESSIONAL
- "Priority Customer" → origin_code: CUSTOMER

SECURITY CLASSES:
- "Penny Symbols" → penny_class: PENNY
- "Non-Penny Symbols" → penny_class: NON_PENNY
- SPY/QQQ/IWM (footnote 6) → symbol: SPY/QQQ/IWM, penny_class: PENNY
- listing_type: EQUITY or ETF (no index products)

TABLE STRUCTURE:
- Regular Orders (Penny): 5 participant rows × (Maker Fee/Rebate Tiers 1-4 | Taker Fee/Rebate Tiers 1-4)
- Regular Orders (Non-Penny): identical structure
- Separate tables for Penny and Non-Penny

INVERTED MAKER/TAKER:
- "Maker Fee/Rebate" column → liquidity_role: MAKER
  - Market Maker: $0.50 (FEE, not rebate) in Penny — they PAY to provide liquidity
  - Priority Customer Tier 2+: ($0.47) REBATE in Penny — they GET PAID to provide
- "Taker Fee/Rebate" column → liquidity_role: TAKER
  - Market Maker: $0.35 (lower fee than maker side)
  - Priority Customer: ($0.31) to ($0.44) REBATE — they GET PAID to take
- Priority Customer vs Priority Customer (footnote 7): $0.00 both sides — no fees, no rebates

4-TIER STRUCTURE:
- Based on Total Customer ADV / Customer Total Consolidated Volume
- Tier 1: up to 0.15%, Tier 2: >0.15-0.40%, Tier 3: >0.40-0.70%, Tier 4: >0.70%
- NON-PRIORITY CUSTOMER FEES ARE FLAT ACROSS ALL TIERS
- Tiers only differentiate Priority Customer rebate levels
- For non-PC rows: extract as tier_level: 0 (base rate, single entry)

CONTRA-PARTY DEPENDENCIES:
- Footnote 8: Non-PC vs Priority Customer → Penny taker = $0.47 (not $0.35)
  → Extract with contra_origin_code: CUSTOMER, fee_value: 0.47
- Footnote 7: PC vs PC → $0.00 both sides
  → Extract with contra_origin_code: CUSTOMER, fee_value: 0.00
- Footnote 3: Affiliated entity discount for Non-Penny taker vs affiliated PC
  → Extract with tier_condition noting affiliated entity

COMPLEX ORDERS (Section 4):
- product_type: COMPLEX
- FLAT fees, NO maker/taker split → liquidity_role: NONE
  - Penny: $0.35 (non-PC), $0.00 (PC)
  - Non-Penny: $0.85 (non-PC), $0.00 (PC)
- Affiliated entity discount: $0.10 when vs affiliated PC
- Stock handling: $0.0010/share (max $50/trade) → fee_type: PER_SHARE
- Legs executing on regular book: use regular table Taker fees

AUCTION TYPES:
- Crossing (FAC, SOL, Block): auction_type: CROSSING
  - Originating + contra: $0.02 (non-PC), $0.00 (PC)
- PIM: auction_type: PIM
  - Originating: $0.20 (non-PC), $0.00 (PC)
  - Contra: $0.02
  - Response: $0.50 Penny, $1.10 Non-Penny
  - Break-up rebate: ($0.25) Penny, ($0.60) Non-Penny for PC
- QCC: auction_type: QCC — $0.20 (non-PC), $0.00 (PC)

SPY/QQQ/IWM (Footnote 6):
- MM Maker: $0.02 (dramatically lower than $0.50 standard)
- PC Taker: ($0.02) rebate (dramatically lower than standard)
- Extract as symbol-specific entries

ROUTING:
- exec_venue: ROUTED
- $0.60 Penny, $1.20 Non-Penny for all participants
```

---

### 3.10 NASDAQ_BX

```
EXCHANGE: Nasdaq BX Options
FORMAT: HTML (same structure as NOM)

NOTE: Fee schedule URL may be stale. BX shares the Nasdaq family structure.
Use the same general approach as NOM with these BX-specific adjustments:

TERMINOLOGY MAPPING:
- Same as NOM: Customer (C), Professional (P), Broker-Dealer (B), Firm (F), Non-BX Market Maker (O), BX Market Maker (M)

SECURITY CLASSES:
- "Penny Symbols" → penny_class: PENNY
- "Non-Penny Symbols" → penny_class: NON_PENNY
- listing_type: EQUITY or ETF

TABLE STRUCTURE:
- Same as NOM: Add Liquidity / Remove Liquidity tables
- Tiers may differ in number and thresholds from NOM

MAKER/TAKER:
- "Add Liquidity" → MAKER
- "Remove Liquidity" → TAKER

Apply the same extraction logic as NOM. Look for footnote-based overrides,
symbol-specific rates, and cross-asset conditions.
```

---

### 3.11 MIAX_OPTIONS

```
EXCHANGE: MIAX Options Exchange
FORMAT: PDF (41 pages, linked from landing page)

TERMINOLOGY MAPPING:
- "Priority Customer" → origin_code: CUSTOMER
- "Public Customer that is Not a Priority Customer" → origin_code: PROFESSIONAL
- "MIAX Market Maker" (includes RMM, LMM, PLMM, DLMM, DPLMM) → origin_code: MARKET_MAKER
- "Non-MIAX Market Maker" → origin_code: AWAY_MARKET_MAKER
- "Non-Member Broker-Dealer" → origin_code: BROKER_DEALER
- "Firm" → origin_code: FIRM

SECURITY CLASSES:
- "Penny Classes" → penny_class: PENNY
- "Non-Penny Classes" → penny_class: NON_PENNY
- "Select Symbols" (56 specific symbols including SPY, QQQ, IWM, AAPL, etc.) → note in fee_name
- listing_type: EQUITY or ETF

TABLE STRUCTURE — MULTIPLE FORMATS:
1. Market Maker Sliding Scale (pp 4-5): rows = tiers, columns = Simple(Penny Maker|Taker, Non-Penny Maker|Taker) | Complex(Penny, Non-Penny) | Complex Surcharge
   TWO versions: "In PC Rebate Tier 3+" and "Not In Tier 3+"
2. Other Participant Fees (pp 6-7): rows = participants, columns = Penny | Non-Penny | Surcharge
   FLAT fees for simple AND complex combined
3. Priority Customer Rebate Program (p 8): 4 tiers × 5 credit columns
4. PRIME/cPRIME tables (pp 12-13): rows = participants, columns = Agency | Contra | Responder(P/NP) | Break-up(P/NP)
5. QCC/cQCC tables (pp 14-15): rows = participants, columns = Initiator | Contra | Rebate by contra origin

MARKET MAKER SLIDING SCALE:
- 5 tiers based on % national MM volume in multiply-listed classes
- TWO tables: one for members in PC Rebate Tier 3+, one for those not
- This cross-references creates a dependency: MM fees depend on BOTH MM volume tier AND PC volume tier
- For extraction: create entries for both variants, note the cross-reference in tier_condition
- Simple orders: Maker/Taker split → liquidity_role: MAKER or TAKER
- Complex orders: single fee (no maker/taker) → liquidity_role: NONE
- Complex surcharge: $0.12 when contra is Priority Customer complex → separate entry with contra_origin_code: CUSTOMER

OTHER PARTICIPANTS (non-MM):
- FLAT fee covers both simple and complex → product_type: SIMPLE and COMPLEX (create entry for each)
- No maker/taker split → liquidity_role: NONE
- Footnote-conditional discounts at PC Rebate Tier 3+/4 → extract as separate tiered entries

PRIORITY CUSTOMER REBATE PROGRAM:
- 4 tiers based on % National Customer Volume
- 5 columns: Simple non-Select | Simple Select | PRIME Agency | cPRIME Agency | Complex
- is_rebate: true for all entries
- "Select Symbols" column → note specific symbol list in fee_name

PROFESSIONAL REBATE PROGRAM:
- 3 tiers based on % volume increase above baseline
- Applies to P, O, B, F origins — liquidity-adding only
- Separate rates for Simple and Complex
- Per-tier (NOT retroactive)

PRIME AUCTION:
- auction_type: PRIME
- Roles: AGENCY, CONTRA, RESPONDER
- Break-up credits with percentage-based adjustments (0-20%, 20-40%, etc.)
- Extract break-up entries with tier_condition: "Break-up >= X%"
- Enhanced break-up at >40%: separate entry

cPRIME AUCTION:
- auction_type: CPRIME
- Same role structure as PRIME
- Per contract per leg
- cPRIME Break-up Table: 10 tiers (0-10% through 90-100%)

QCC / cQCC:
- auction_type: QCC or CQCC
- Minimum 1,000 contracts
- Rebates vary by contra origin:
  - contra PC → one rebate amount
  - contra Public Customer (not PC) → different amount
  - contra all others → different amount
- Extract 3 entries per origin with different contra_origin_code values

C2C / cC2C:
- auction_type: C2C or CC2C
- $0.00 per contract

COMPLEX SURCHARGE:
- $0.12 per contract on non-PC trading against PC complex order
- Applies on Strategy Book and complex auctions (excluding cPRIME)
- contra_origin_code: CUSTOMER

ROUTING:
- exec_venue: ROUTED
- Destination-specific fees (different amounts per away exchange)
- Split by origin type and Penny/Non-Penny

MARKETING FEE:
- $0.25/contract Penny, $0.70/contract Non-Penny
- Paid by Market Makers into a pool controlled by LMM/PLMM
- Extract as fee_type: PER_CONTRACT with fee_name: "Marketing Fee"
```

---

### 3.12 MIAX_PEARL

```
EXCHANGE: MIAX Pearl Options
FORMAT: PDF (34 pages)

TERMINOLOGY MAPPING:
- "Priority Customer" → origin_code: CUSTOMER
- "Non-Priority Customer" (Public Customer not Priority) → origin_code: PROFESSIONAL
- "MIAX Pearl Market Maker" → origin_code: MARKET_MAKER
- "Non-MIAX Pearl Market Maker" → origin_code: AWAY_MARKET_MAKER
- "Firm" → origin_code: FIRM
- "BD" (Broker-Dealer) → origin_code: BROKER_DEALER

SECURITY CLASSES:
- "Penny Classes" → penny_class: PENNY
- "Non-Penny Classes" → penny_class: NON_PENNY
- SPY → symbol: SPY (separate taker column for Priority Customer)
- QQQ/IWM → symbol: QQQ or IWM (grouped in separate taker column)

TABLE STRUCTURE — THREE SEPARATE TABLES by origin group:
1. Priority Customer table (p 8): Penny columns = Maker | Taker* | SPY Taker | QQQ/IWM Taker; Non-Penny = Maker | Taker
2. Market Maker table (p 9): Penny columns = Maker(contra ex PC) | Maker(contra PC) | Taker(contra ex PC) | Taker(contra PC); Non-Penny same
3. Non-Priority/Firm/BD/Away MM table (p 10): same structure as MM table

MAKER/TAKER:
- "Maker" → liquidity_role: MAKER (rebates in parentheses)
- "Taker" → liquidity_role: TAKER

CONTRA-PARTY DEPENDENT MAKER REBATES:
- MM and Non-Priority tables split Maker by contra:
  - "Contra Origins ex Priority Customer" → contra_origin_code: ANY (non-CUSTOMER)
  - "Contra Priority Customer Origin" → contra_origin_code: CUSTOMER
- Rebate when contra is PC is consistently $0.03 lower than when contra is non-PC
- Taker fees are flat regardless of contra

SPY/QQQ/IWM BREAKOUT:
- Priority Customer table has separate taker columns for SPY and QQQ/IWM
- Extract as symbol-specific entries: symbol: SPY, symbol: QQQ (or QQQ_IWM group)

6-TIER STRUCTURE:
- Three independent tier tables (one per origin group)
- Priority Customer: based on % TCV in Priority Customer origin
- Market Maker: based on % TCV in MM origin, with ALTERNATIVE criteria for Tiers 2-4 (SPY/QQQ/IWM-specific volume)
- Non-Priority: based on % TCV
- Alternative tier criteria: extract both paths in tier_condition with OR logic

NO PRIME/AUCTION:
- MIAX Pearl does NOT have PRIME or cPRIME auctions
- No separate auction fee tables

NO COMPLEX ORDER DISTINCTION:
- Same fees for simple and complex → product_type: SIMPLE (or ALL)
- All fees per contract per leg

ROUTING:
- exec_venue: ROUTED
- Destination-specific fees (grouped by away exchange)
- Split by Priority Customer vs others, and Penny vs Non-Penny

SPECIAL RULES:
- Transaction fees WAIVED for opening transactions and ABBO uncrossing
- Affiliate volume aggregation (75% ownership)
- Appointed Market Maker / Appointed EEM designations for volume aggregation
```

---

### 3.13 MIAX_EMERALD

```
EXCHANGE: MIAX Emerald Options
FORMAT: PDF (37 pages)

TERMINOLOGY MAPPING:
- "Priority Customer" → origin_code: CUSTOMER
- "Non-Priority Customer" → origin_code: PROFESSIONAL
- "Market Maker" (LMM, PLMM, RMM collectively) → origin_code: MARKET_MAKER
- "Non-MIAX Emerald Market Maker" → origin_code: AWAY_MARKET_MAKER
- "Firm Proprietary/Broker-Dealer" → origin_code: FIRM (combined row)

SECURITY CLASSES:
- "Penny Classes" → penny_class: PENNY
- "Non-Penny Classes" → penny_class: NON_PENNY
- SPY/QQQ/IWM special rebates → symbol: SPY/QQQ/IWM

TABLE STRUCTURE — SINGLE TABLE PER SECURITY CLASS:
- Penny table (p 8) and Non-Penny table (p 9)
- Each has 9 data columns grouped:
  Simple: Maker | Taker
  Complex: Maker(contra ex PC) | Maker(contra PC) | Taker | Surcharge
  PRIME/cPRIME: Agency | Contra | Responder
- Rows = origin type × tier (1-4)

MAKER/TAKER:
- Simple: standard Maker/Taker
- Complex: Maker split by contra-party, Taker flat
- PRIME/cPRIME: role-based (Agency/Contra/Responder)

4-TIER STRUCTURE with 3 ALTERNATIVE METHODS:
- Method 1: Total Member sides as % of CTCV
- Method 2: Total Emerald MM sides as % of CTCV
- Method 3: Total Priority Customer Maker sides as % of CTCV
- Priority Customer uses Method 3 ONLY
- All others use HIGHEST tier among all three methods

COMPLEX ORDERS:
- product_type: COMPLEX
- Maker varies by contra: contra_origin_code: CUSTOMER vs non-CUSTOMER
  - MM T1 Penny: $0.10 (contra non-PC) vs $0.47 (contra PC) — big difference
- Complex Surcharge: $0.12 for non-PC origins vs PC complex orders
- PC Complex vs Complex: $0.00 (neither charged nor rebated)
- PC Complex removing from Simple book: $0.20 Penny, $0.40 Non-Penny

PRIME/cPRIME:
- auction_type: PRIME or CPRIME
- Three roles: AGENCY, CONTRA, RESPONDER
- Preexisting contra-side interest: fee waived
- Responder trades at Simple or Complex rates (not PRIME rates)

QCC/cQCC:
- auction_type: QCC or CQCC
- Per contract fee for Initiator and Contra-side
- Rebate varies (no rebate when both sides are PC)

C2C/cC2C:
- auction_type: C2C or CC2C — $0.00

FOOTNOTE SYMBOLS (act as modifiers):
- ^ = taker fee details for contra PC simple orders
- * = PC complex-vs-complex and legging rules
- ~ = surcharge on non-PC vs PC complex
- # = complex auction: PC gets taker rebate when contra non-PC
- ! = MM maker rebate reduced $0.02/tier when contra PC in Penny
- (diamond) = PRIME waiver for preexisting contra interest
- (filled diamond) = special PC maker rebate with affiliated MM conditions
- Extract each footnote modifier as a separate fee entry or condition

SPY/QQQ/IWM SPECIAL:
- PC Simple Maker in SPY/QQQ/IWM: ($0.45) for Tiers 1-3 when contra is NOT affiliated MM
- When contra IS affiliated MM: ($0.37)
- With both MM sides >= 0.90% AND PC Maker >= 0.60%: ($0.43)
- Extract as symbol-specific entries with tier_condition

ROUTING:
- exec_venue: ROUTED
- Destination-specific fees per away exchange
```

---

### 3.14 MIAX_SAPPHIRE

```
EXCHANGE: MIAX Sapphire Options
FORMAT: PDF (39 pages)

TERMINOLOGY MAPPING:
- "Priority Customer" → origin_code: CUSTOMER
- "Non Priority Customer/Non Market Maker" (composite category) → origin_code: PROFESSIONAL
  NOTE: This composite covers Professional, Away MM, BD, Firm. Map to P as primary.
  When QCC/cQCC tables break these out separately, use appropriate codes.
- "MIAX Sapphire Market Maker" → origin_code: MARKET_MAKER
- In QCC tables, additional granularity appears:
  - "Public Customer that is not a Priority Customer" → P
  - "Non-MIAX Sapphire Market Maker" → O
  - "Non-Member Broker-Dealer" → B
  - "Firm" → F

SECURITY CLASSES — THREE-WAY SPLIT:
- "SPY, QQQ, and IWM" → symbol: SPY/QQQ/IWM, penny_class: PENNY
- "Penny Classes (excluding SPY, QQQ, and IWM)" → penny_class: PENNY
- "Non-Penny Classes" → penny_class: NON_PENNY

DUAL VENUE — ELECTRONIC + PHYSICAL FLOOR:
- Electronic tables: Maker/Taker split
- Floor tables: FLAT fees (no maker/taker)
- exec_venue: ELECTRONIC or FLOOR

TABLE STRUCTURE:
- Electronic Transaction Fees: rows = origin, columns per security class group = Maker | Taker
- Floor Transaction Fees: rows = origin, columns per security class = flat fee
- QFO/cQFO tables: role-based
- QCC/cQCC tables: Initiator/Contra/Rebate

NO VOLUME-BASED TIERS in core transaction fees
- tier_level: 0 for all core transaction fees
- Tiered structures only in membership/port fees

ELECTRONIC FEES:
- liquidity_role: MAKER or TAKER
- Rebates in parentheses

FLOOR FEES:
- liquidity_role: NONE (flat per-contract)
- exec_venue: FLOOR

QFO (Qualified Floor Order):
- auction_type: QFO
- Physical floor-based execution mechanism
- Roles: Agency, Contra, Responder
- Floor Broker rebates for presenting orders
- Strategy-based fee caps (dividend, merger, reversal, etc.)

cQFO (Complex Qualified Floor Order):
- auction_type: CQFO
- Complex version of QFO
- Per contract per leg

PRIME/cPRIME:
- auction_type: PRIME or CPRIME
- Electronic auction mechanism
- Roles: AGENCY, CONTRA, RESPONDER

QCC/cQCC:
- auction_type: QCC or CQCC
- Minimum 1,000 contracts
- Granular participant breakdown in QCC tables

COMPLEX ORDERS:
- Electronic complex: separate columns
- Complex Surcharge: for non-PC origins trading against PC complex
- Floor complex: flat fee via cQFO mechanism

ROUTING:
- exec_venue: ROUTED
- Destination-specific fees

SPECIAL RULES:
- Opening and ABBO uncrossing: fees waived
- Newest MIAX exchange — some fees may still be in "Waiver Period"
```

---

### 3.15 NYSE_ARCA

```
EXCHANGE: NYSE Arca Options
FORMAT: PDF (22 pages)

TERMINOLOGY MAPPING:
- "Customer" → origin_code: CUSTOMER
- "Professional Customer" → origin_code: PROFESSIONAL (treated as Customer for most purposes UNLESS delineated)
- "LMM" (Lead Market Maker) → origin_code: MARKET_MAKER
- "NYSE Arca Market Maker" → origin_code: MARKET_MAKER
- "Firm" ("F" origin) → origin_code: FIRM
- "Broker Dealer" → origin_code: BROKER_DEALER
- "Non-Customer" = F, B, M (collective term)
- "Floor Broker" → note in fee_name

SECURITY CLASSES:
- "Penny" issues → penny_class: PENNY
- "non-Penny" issues → penny_class: NON_PENNY
- SPY → symbol: SPY (separate LMM rate, MM incentive tiers)
- MXEA/MXEF → listing_type: INDEX, symbol as given
- BKX → listing_type: INDEX, symbol: BKX (Royalty Fee)

TABLE STRUCTURE:
- Electronic Execution (p 7): rows = participants, columns = Post Liquidity(Penny) | Take Liquidity(Penny) | Post Liquidity(Non-Penny) | Take Liquidity(Non-Penny)
- Manual Execution (pp 5-6): rows = participants, columns = MXEA/MXEF rate | Other Manual rate
- QCC (pp 7-8): simple table + tiered credits
- Complex Orders (p 15): origin × contra grid
- Many independent tier tables (pp 8-16)

MAKER/TAKER:
- "Post Liquidity" → liquidity_role: MAKER
- "Take Liquidity" → liquidity_role: TAKER
- Parenthetical amounts = credits/rebates
- Professional Customer posting credits capped at ($0.49) Penny / ($1.00) Non-Penny

ELECTRONIC vs MANUAL:
- exec_venue: ELECTRONIC for standard Post/Take
- exec_venue: FLOOR for Manual Execution
- MXEA/MXEF have separate manual rates

COMPLEX ORDERS:
- Complex vs Complex: origin/contra grid (3×2):
  CUSTOMER vs non-CUSTOMER: Customer gets credit, Non-Customer pays fee
  CUSTOMER vs CUSTOMER: $0.00
  non-CUSTOMER vs non-CUSTOMER: standard fee
- Complex vs Consolidated Book (individual orders): Take Liquidity rate applies
- Non-Customer Complex Surcharge: $0.12 (reduced to $0.05/$0.07 with volume)
- Customer Complex Credit Tiers: Base through Tier 4

TIERS (many independent programs):
- Customer Penny Posting Credit: Base + 6 tiers (% of TCADV)
- Firm/BD Penny Posting Credit: Base + 2 tiers
- Non-Customer Non-Penny Posting Credit: 4 tiers
- Customer Non-Penny Posting Credit: Base + Tiers A-F
- Customer Take Fee Discount: 2 tiers
- Market Maker Penny + SPY Posting Credit: 6 named tiers (Base, Select, Super, Super II, Super Select, Super Select II)
- QCC Additional Credits: 2 tiers (absolute volume: 1.5M, 3.5M contracts)
- Customer Complex Credit: Base + 4 tiers
- Cross-market tiers require NYSE Arca Equity Market activity → note in tier_condition

QCC:
- auction_type: QCC
- Non-Customer: $0.20, Customer: $0.00
- Submitting Broker credits vary by trade composition
- Volume excluded from Post/Take calculations

STRATEGY EXECUTIONS:
- $200 cap per execution for reversals, box spreads, short stock interest, merger, jelly rolls, dividends
- QCC executing strategy: NOT eligible for cap (except reversals/conversions)

ROUTING:
- exec_venue: ROUTED
- $0.61 Penny, $1.21 Non-Penny IN ADDITION TO customary fees
- Floor Brokers exempt

OPENING:
- "Transaction fees do not apply to executions occurring during the Opening Auction"
- auction_type: OPENING, fee_value: 0.00

SPECIAL:
- Appointed OFP/MM system for volume aggregation (12-month lock-in)
- BKX Royalty Fee: $0.10/contract → listing_type: INDEX, symbol: BKX
- MXEA/MXEF Index License Surcharge: $0.20 for Non-Customer
```

---

### 3.16 NYSE_AMERICAN

```
EXCHANGE: NYSE American Options
FORMAT: PDF (40 pages)

TERMINOLOGY MAPPING:
- "Customer" → origin_code: CUSTOMER
- "Professional Customer" → origin_code: PROFESSIONAL
- "NYSE American Options Market Maker" → origin_code: MARKET_MAKER
- "Non-NYSE American Options Market Maker" → origin_code: AWAY_MARKET_MAKER
- "Firm" → origin_code: FIRM
- "Broker-Dealer" → origin_code: BROKER_DEALER
- "DOMM" (Directed Order Market Maker) → origin_code: MARKET_MAKER (sub-type)
- "e-Specialist" / "Specialist" → origin_code: MARKET_MAKER (sub-type)
- "Firm Facilitation" → origin_code: FIRM, exec_venue: FLOOR, note facilitation

SECURITY CLASSES:
- "Penny" → penny_class: PENNY
- "Non-Penny" → penny_class: NON_PENNY
- NOTE: Penny/Non-Penny appears as ROW values in main table, not column headers
- Premium Products (SPY, AAPL, IWM, QQQ, TSLA, AMZN, NVDA, META, AMD, VXX) → note in fee_name
- BKX → listing_type: INDEX, symbol: BKX

TABLE STRUCTURE:
- Main Transaction Fees (pp 7-8): 5 columns — Participant | Penny/Non-Penny | Electronic Rate | Marketing Charge | Manual Rate
  Each participant has TWO rows (one Penny, one Non-Penny)
- MM Sliding Scale (pp 9-10): 4 tiers × (Non-Take Volume | Take Volume) with standard and Prepayment variants
  TWO versions: through June 30 2026 and effective July 1 2026
- ACE Program (p 14): 6 tiers × (Simple Credit | Complex Credit | Enhanced Simple | Enhanced Complex)
- CUBE (pp 16-19): separate tables for Single-Leg, Complex, AON
- QCC (p 15): simple 2-column table

HYBRID FEE MODEL:
- Main table: FLAT per-contract fee (no maker/taker for most participants) → liquidity_role: NONE
- MM Sliding Scale: HAS maker/taker → "Non-Take Volume" = MAKER, "Take Volume" = TAKER
- This is a HYBRID model — flat for most, maker/taker for MMs only

MARKET MAKER SLIDING SCALE:
- 4 tiers based on MM Electronic ADV as % of TCADV
- MARGINAL tiers (lower rate applies only to volume within that tier)
- Two versions with different thresholds (pre/post July 1 2026) — extract both with effective dates
- Prepayment Program variant: lower rates for members who prepay annual fees
- Extract standard and prepayment as separate tier groups

ACE PROGRAM (American Customer Engagement):
- 6 tiers (Base, 1-5) based on Customer Electronic ADV as % of TCADV
- Dual qualification: Customer-only ADV OR Total ADV (with 20% Customer minimum)
- Credits are RETROACTIVE to first contract
- Separate columns for Simple and Complex credits → product_type
- Enhanced credits for 1-year commitment
- is_rebate: true for all ACE entries

CUBE AUCTION:
- auction_type: CUBE
- Single-Leg CUBE: CUBE Order (Customer $0.00, Non-Customer $0.20), Contra Order ($0.05), RFR Response
- Complex CUBE: Contra $0.05 Penny / $0.07 Non-Penny, RFR Response $0.50 Penny / $1.05 Non-Penny
- AON CUBE: minimum 500 contracts, Contra $0.20
- Initiating Participant Credit: tiered by ACE tier
- auction_role: AGENCY (CUBE Order), CONTRA (Contra Order), RESPONDER (RFR Response), INITIATOR (credit)

QCC:
- auction_type: QCC
- C/P: $0.00, M/F/B: $0.20
- Floor Broker credits by composition

BOLD MECHANISM:
- auction_type: BOLD
- Customer Initiating: ($0.12) or ($0.13) if ACE-eligible
- Customer Responding: $0.00
- Non-Customer: standard transaction fees from main table

ELECTRONIC vs MANUAL:
- Main table has separate columns for Electronic and Manual rates
- exec_venue: ELECTRONIC or FLOOR
- Firm Facilitation (Manual only): $0.00

MARKETING CHARGES:
- MM liable when counterparty to electronic Customer trades
- Extract as separate fee entries with fee_name: "Marketing Charge"

DUAL EFFECTIVE DATES:
- MM Sliding Scale has two versions (through June 30 vs effective July 1)
- Extract both with appropriate effective_date values

NON-CUSTOMER COMPLEX SURCHARGE:
- $0.12 on Non-Customer Complex vs Customer Complex
- Reduced to $0.10 for ATP Holders at >= 0.20% TCADV
- Does NOT apply in CUBE Auctions

STRATEGY EXECUTION CAP:
- $1,000 (or $200 for high-volume) cap on reversals, box spreads, etc.
```

---

### 3.17 BOX_OPTIONS

```
EXCHANGE: BOX Options Exchange
FORMAT: PDF (22 pages, linked from landing page)

TERMINOLOGY MAPPING:
- "Public Customer" → origin_code: CUSTOMER
- "Professional Customer" → origin_code: PROFESSIONAL
- "Broker Dealer" → origin_code: BROKER_DEALER
  NOTE: Sometimes grouped as "Professional Customer or Broker Dealer" → extract as P (or B when split)
- "Market Maker" (includes Electronic MM and Floor MM) → origin_code: MARKET_MAKER

SECURITY CLASSES — THREE-WAY SPLIT:
- "Penny Interval Classes" → penny_class: PENNY
- "Non-Penny Interval Classes" → penny_class: NON_PENNY
- "SPY, QQQ, and IWM" → symbol: SPY/QQQ/IWM, penny_class: PENNY (separate column)

*** FULL NxN ORIGIN/CONTRA GRID — BOX'S MOST DISTINCTIVE FEATURE ***

TABLE STRUCTURE (Non-Auction, Section IV.A):
- 3×3 matrix: Origin (C, P/B, M) × Contra (C, P/B, M)
- Each cell has 6 values: Penny Maker | Penny Taker | Non-Penny Maker | Non-Penny Taker | SPY Maker | SPY Taker
- Extract EVERY cell as a separate fee entry with origin_code AND contra_origin_code

ORIGIN/CONTRA GRID EXTRACTION:
Row: Public Customer, Contra: Public Customer → origin_code: CUSTOMER, contra_origin_code: CUSTOMER
Row: Public Customer, Contra: Prof Cust/BD → origin_code: CUSTOMER, contra_origin_code: PROFESSIONAL
Row: Public Customer, Contra: Market Maker → origin_code: CUSTOMER, contra_origin_code: MARKET_MAKER
Row: Prof Cust/BD, Contra: Public Customer → origin_code: PROFESSIONAL, contra_origin_code: CUSTOMER
Row: Prof Cust/BD, Contra: Prof Cust/BD → origin_code: PROFESSIONAL, contra_origin_code: PROFESSIONAL
Row: Prof Cust/BD, Contra: Market Maker → origin_code: PROFESSIONAL, contra_origin_code: MARKET_MAKER
Row: Market Maker, Contra: Public Customer → origin_code: MARKET_MAKER, contra_origin_code: CUSTOMER
Row: Market Maker, Contra: Prof Cust/BD → origin_code: MARKET_MAKER, contra_origin_code: PROFESSIONAL
Row: Market Maker, Contra: Market Maker → origin_code: MARKET_MAKER, contra_origin_code: MARKET_MAKER

MAKER/TAKER:
- Explicit Maker/Taker columns within each cell
- C Maker/Taker: typically $0.00 (free for Public Customer)
- P/B and M: Maker fees lower than Taker fees

COMPLEX ORDERS (Section VI.A):
- product_type: COMPLEX
- SAME NxN grid structure as Non-Auction but with different rates
- Complex Surcharge: $0.12 on non-CUSTOMER complex vs CUSTOMER complex (waived for SPY/QQQ/IWM under conditions)
- All complex fees are per contract per leg

PIP (Price Improvement Period):
- auction_type: PIP
- PIP Order = Agency Order (Customer), Primary Improvement Order = Contra
- Improvement Orders = Responses
- Break-Up Credit when PIP order doesn't fully trade with its Primary Improvement Order
- Tiered Primary Improvement Order fee (2 tiers based on National Customer Volume)

COPIP (Complex Order PIP):
- auction_type: COPIP
- Same structure as PIP for complex orders
- Per contract per leg

BOX Volume Rebate (PIP/COPIP):
- 4 tiers with separate PIP and COPIP rebate columns

FACILITATION/SOLICITATION:
- auction_type: FAC or SOL
- Roles: AGENCY, CONTRA (Facilitation/Solicitation Order), RESPONDER
- Break-Up Credit
- Strategy Order Facilitation/Solicitation: Prof Customer and BD split with DIFFERENT rates

QCC:
- auction_type: QCC
- Minimum 1,000 contracts
- Agency + Contra structure
- Rebate 1 (one side BD/MM) vs Rebate 2 (both sides BD/MM) → 2 rebate tiers
- QCC Growth Rebate: cross-product volume incentive

MANUAL TRANSACTIONS:
- exec_venue: FLOOR
- QOO (Qualified Open Outcry): simple, floor-based
- FOO (FLEX Open Outcry): FLEX, floor-based
- Floor Broker rebates for presenting orders
- Enhanced rebates for trades with Floor Market Maker

OPENING/RE-OPENING:
- auction_type: OPENING
- Separate fee table

TIERED REBATES:
- MM Tiered Volume Rebate: 4 tiers (% national MM volume)
- Public Customer Tiered Volume Rebate: 5 tiers, split by Penny/Non-Penny/SPY,QQQ,IWM and Maker/Taker
- PIP Primary Improvement Order: 2 tiers
- BOX Volume Rebate: 4 tiers
- QCC Rebate: 3 tiers (absolute volume)

STRATEGY ORDERS:
- Specific fee caps for: short/long stock interest, merger, reversal, conversion, jelly roll, box spread, dividend
- Dividend strategy caps: $1,000/day, $65,000/month
- Strategy QCC: free, excluded from volume

ROUTING:
- exec_venue: ROUTED
- $0.60 Penny, $0.85 Non-Penny for customer accounts
```

---

### 3.18 MEMX_OPTIONS

```
EXCHANGE: MEMX Options Exchange
FORMAT: HTML + CSV (CSV is authoritative source)

TERMINOLOGY MAPPING:
- "Customer" (c) → origin_code: CUSTOMER
- "Professional" (p) → origin_code: PROFESSIONAL
- "Market Maker" (m) → origin_code: MARKET_MAKER
- "Firm" (f) → origin_code: FIRM
- "Away Market Maker" (a) → origin_code: AWAY_MARKET_MAKER
- "Broker-Dealer" (b) → origin_code: BROKER_DEALER

SECURITY CLASSES:
- "Penny" (P) → penny_class: PENNY
- "Non-Penny" (N) → penny_class: NON_PENNY
- No index products, no symbol-specific rates
- listing_type: EQUITY or ETF

*** COMPOSITE FEE CODE ENCODING — MEMX'S UNIQUE FEATURE ***

FEE CODE PATTERN: [Action][Capacity][TierNumber?][SecurityClass]
- Position 1 (Action): D = Add (MAKER), R = Remove (TAKER), Z = Routed
- Position 2 (Capacity): c/m/p/f/a/b (lowercase)
- Position 3 (optional): 1 = Tier number
- Position 4 (last, uppercase): P = Penny, N = Non-Penny

EXAMPLES:
- DcP = Add + Customer + Penny → MAKER, origin: CUSTOMER, penny_class: PENNY
- RmN = Remove + Market Maker + Non-Penny → TAKER, origin: MARKET_MAKER, penny_class: NON_PENNY
- Dp1P = Add + Professional + Tier 1 + Penny → MAKER, origin: PROFESSIONAL, penny_class: PENNY, tier_level: 1
- ZcP = Routed + Customer + Penny → ROUTED, origin: CUSTOMER, penny_class: PENNY

COMPLETE FEE CODE INVENTORY (33 codes):
- Add (D): DaN, DbN, DcN, DfN, DmN, DpN, DaP, DbP, DcP, DfP, DmP, DpP, Dp1P
- Remove (R): RaN, RbN, RcN, RfN, RmN, RpN, RaP, RbP, RcP, RfP, RmP, RpP
- Routed (Z): ZbN, ZcN, ZfN, ZpN, ZbP, ZcP, ZfP, ZpP
- NOTE: No routing for Away MM (a) or Market Maker (m)

TABLE STRUCTURE:
- Single 4-column grid: Penny-Add | Penny-Remove | Non-Penny-Add | Non-Penny-Remove
- 6 participant rows
- IMPORTANT: HTML table shows dashes for Firm/Away MM/BD — but CSV has actual values. USE CSV.

MAKER/TAKER:
- Add (D) = MAKER → rebates (negative amounts)
- Remove (R) = TAKER → fees (positive amounts)
- Pure maker/taker model

SINGLE TIER:
- Only Professional Penny Add has a tier: Dp1P
- tier_level: 1, tier_condition: "Member ADAV in C/P/F/O/B capacity in Penny >= 0.125% of equity+ETF option TCV"

NO COMPLEX ORDERS:
- No complex order distinction → product_type: SIMPLE

NO AUCTIONS:
- No PRIME, PIM, QCC, FLEX, or any auction mechanisms

NO CONTRA GRIDS:
- Fees depend only on origin capacity, not contra party

ROUTING:
- Z-prefix codes → exec_venue: ROUTED
- Flat fee regardless of destination exchange
- Not available for MM (m) or Away MM (a)

THIS IS THE SIMPLEST FEE SCHEDULE of all 18 exchanges.
Total: 33 fee entries.
```

---

## 4. Implementation Notes

### 4.1 Storage Location
Store prompts in `src/exnot/ai/prompts/` with one file per exchange:
```
src/exnot/ai/prompts/
├── __init__.py
├── base.py              # Shared output schema definition
├── cboe_bzx.py
├── cboe_edgx.py
├── cboe_c1.py
├── cboe_c2.py
├── nasdaq_ise.py
├── nasdaq_nom.py
├── nasdaq_phlx.py
├── nasdaq_gemx.py
├── nasdaq_mrx.py
├── nasdaq_bx.py
├── miax_options.py
├── miax_pearl.py
├── miax_emerald.py
├── miax_sapphire.py
├── nyse_arca.py
├── nyse_american.py
├── box_options.py
└── memx_options.py
```

### 4.2 Prompt Assembly
```python
def get_extraction_prompt(exchange_code: str) -> str:
    base = BASE_PROMPT  # Output schema, sign conventions, general rules
    exchange_prompt = EXCHANGE_PROMPTS[exchange_code]
    return f"{base}\n\n{exchange_prompt}"
```

### 4.3 Base Prompt (shared across all exchanges)
The base prompt defines:
- The output schema (all fields listed in Section 2)
- Sign conventions (parentheses = rebate, negative = rebate)
- General extraction rules (extract ALL fees, include tiers, include footnote-modified entries)
- Fee type mapping rules
- Amount precision requirements

### 4.4 Integration Points
- Replace `extraction_hints.py` with the new per-exchange prompts
- Modify `section_extractor.py` to use `get_extraction_prompt(exchange_code)` instead of generic EXTRACTION_RULES + hints
- Update `ai/types.py` with new `ExtractedFee` model matching the schema
- Update `normalizer/schema.py` with new enums (origin_code, exec_venue, etc.)
- Update `db/models.py` with new NormalizedFee columns
