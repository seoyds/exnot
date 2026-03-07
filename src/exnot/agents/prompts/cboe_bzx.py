"""Cboe BZX Options Exchange extraction prompt."""

PROMPT = """\
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
"""
