"""MEMX Options Exchange extraction prompt."""

PROMPT = """\
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
"""
