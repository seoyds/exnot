"""NYSE Arca Options extraction prompt."""

PROMPT = """\
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
"""
