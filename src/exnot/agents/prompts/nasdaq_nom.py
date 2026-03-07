"""Nasdaq Options Market (NOM) extraction prompt."""

PROMPT = """\
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
"""
