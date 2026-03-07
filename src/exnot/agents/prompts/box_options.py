"""BOX Options Exchange extraction prompt."""

PROMPT = """\
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
"""
