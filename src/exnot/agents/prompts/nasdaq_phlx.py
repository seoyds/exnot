"""Nasdaq PHLX extraction prompt."""

PROMPT = """\
EXCHANGE: Nasdaq PHLX
FORMAT: HTML (text-formatted tables, NOT semantic HTML tables)

TERMINOLOGY MAPPING:
- "Customer" → origin_code: CUSTOMER
- "Professional" → origin_code: PROFESSIONAL
- "Lead Market Maker" / "Market Maker" (often grouped as "LMM/MM") → origin_code: MARKET_MAKER
- "Broker-Dealer" (includes JBO) → origin_code: BROKER_DEALER
- "Firm" → origin_code: FIRM
- "Directed Market Maker" → origin_code: MARKET_MAKER (sub-type, note in fee_name)
- "Non-Customer" = PROFESSIONAL, FIRM, BROKER_DEALER, MARKET_MAKER, AWAY_MARKET_MAKER

SECURITY CLASSES:
- "Penny Symbol" → penny_class: PENNY
- "Non-Penny Symbol" → penny_class: NON_PENNY
- SPY → ENTIRELY SEPARATE section (Section 3), symbol: SPY, penny_class: PENNY
- NDX/NDXP/EXGN/XND → listing_type: INDEX, symbol as given
- "Singly Listed" (Section 5.C) → multi_listed: false
- "FX Options" (Section 5.D) → listing_type: INDEX, note symbols

DUAL VENUE — ELECTRONIC vs FLOOR:
- Section 4 has BOTH Electronic and Floor rows for each participant × Penny/Non-Penny
- exec_venue: ELECTRONIC or FLOOR
- Monthly Market Maker Cap ($650,000) applies ONLY to electronic
- Monthly Firm Fee Cap ($250,000) applies ONLY to floor

TABLE STRUCTURE:
- Section 3 (SPY): Part A = Simple, Part B = Complex, Part C = PIXL
- Section 4 (Multiply Listed): rows = Electronic Penny | Electronic Non-Penny | Floor Penny | Floor Non-Penny
  columns = Customer | Professional | LMM/MM | Broker-Dealer | Firm
- Crossing Order tables: columns = Crossing Order Fee | Response Fee | Breakup Rebate
- Customer Rebate Program: 5 tiers × 4 categories (A/B = simple, C/D = complex penny/non-penny)

MAKER/TAKER:
- "Add Liquidity" → MAKER
- "Remove Liquidity" → TAKER
- SPY LMM/MM Add: 6-tier rebate schedule

COMPLEX ORDERS:
- product_type: COMPLEX
- Customer Rebate Categories C and D are complex-specific
- Footnote [2]: complex orders at different rate ($0.40)
- Surcharges [6],[7]: $0.12 for complex removing liquidity
- SPY Complex (Part B): entirely separate table from SPY Simple (Part A)
- Complex Order Surcharge: $0.15 for SPY customer complex vs MM/LMM simple quotes

AUCTION TYPES:
- PIXL (Price Improvement by Xchange): auction_type: PIXL
  - Initiating Order, PIXL Order, PIXL Response (during/prior auction)
  - Complex PIXL rebate for >499 contracts
  - SPY PIXL: separate rates in Section 3.C
- Crossing Orders (FAC/SOL): auction_type: FAC or SOL
  - Separate tables for simple penny, simple non-penny, complex
  - Columns: crossing fee | response fee | breakup rebate
- QCC: auction_type: QCC
  - $0.20 transaction fee, multi-tier rebate
- Order Exposure Alert: SPY-specific, auction_type: CROSSING

TIERS:
- Customer Rebate: 5 tiers based on % National Customer Volume
- SPY LMM/MM Add: 6 tiers based on % Total Cleared Customer Volume
- Floor Broker Incentive: 4 tiers based on absolute contract count
- QCC Rebate: 3 tiers
- MARS: 7 tiers based on ADV

XND INCENTIVE PROGRAM (3D MATRIX):
- listing_type: INDEX, symbol: XND
- 6 premium brackets × 3 expiration buckets × quoting width requirement
- Extract as individual entries with tier_condition describing the 3D position
- Premium ranges: $0-$1, $1.01-$3, $3.01-$5, $5.01-$10, $10.01-$25, >$25
- Expiration buckets: 14 days, 15-60 days, 61+ days
- Cumulative rebate up to $0.05 for heightened quoting standards

INDEX OPTIONS (Section 5):
- NDX/NDXP: Multiple stacking surcharges ($0.25 + $0.50 + $1.50 for non-customer)
- Extract surcharges as SEPARATE fee entries
- NDX premium surcharge: $0.25 for premium >= $25.00 → tier_condition

SPECIAL RULES:
- SPY excluded from Customer Rebate Program and Marketing Fees
- Broad-based index options excluded from Customer Rebate Program rebates (but volume counts)
- Floor Originated Strategy Executions: rebates for dividend, merger, reversal, etc.
- Conditional footnotes with stacking modifiers (*,#,&,**) — extract each as separate entry
- Multiple overlapping monthly caps
"""
