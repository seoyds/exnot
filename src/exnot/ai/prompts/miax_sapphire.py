"""MIAX Sapphire Options extraction prompt."""

PROMPT = """\
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
"""
