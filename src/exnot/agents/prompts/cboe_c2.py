"""Cboe C2 Options Exchange extraction prompt."""

PROMPT = """\
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
"""
