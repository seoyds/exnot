"""MIAX Pearl Options extraction prompt."""

PROMPT = """\
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
"""
