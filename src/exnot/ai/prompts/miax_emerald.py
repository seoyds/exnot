"""MIAX Emerald Options extraction prompt."""

PROMPT = """\
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
"""
