"""Nasdaq GEMX extraction prompt."""

PROMPT = """\
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
"""
