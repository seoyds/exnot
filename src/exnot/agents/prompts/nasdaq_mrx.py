"""Nasdaq MRX extraction prompt."""

PROMPT = """\
EXCHANGE: Nasdaq MRX (Mercury)
FORMAT: HTML with tiered tables

*** CRITICAL: MRX USES AN INVERTED MAKER/TAKER MODEL ***
- Market Makers PAY MORE to MAKE (provide liquidity) than to TAKE
- Priority Customers receive REBATES as TAKERS
- This is the OPPOSITE of most exchanges

TERMINOLOGY MAPPING:
- "Market Maker" → origin_code: MARKET_MAKER
- "Non-Nasdaq MRX Market Maker (FarMM)" → origin_code: AWAY_MARKET_MAKER
- "Firm Proprietary/Broker-Dealer" → origin_code: FIRM (combined row)
- "Professional Customer" → origin_code: PROFESSIONAL
- "Priority Customer" → origin_code: CUSTOMER

SECURITY CLASSES:
- "Penny Symbols" → penny_class: PENNY
- "Non-Penny Symbols" → penny_class: NON_PENNY
- SPY/QQQ/IWM (footnote 6) → symbol: SPY/QQQ/IWM, penny_class: PENNY
- listing_type: EQUITY or ETF (no index products)

TABLE STRUCTURE:
- Regular Orders (Penny): 5 participant rows × (Maker Fee/Rebate Tiers 1-4 | Taker Fee/Rebate Tiers 1-4)
- Regular Orders (Non-Penny): identical structure
- Separate tables for Penny and Non-Penny

INVERTED MAKER/TAKER:
- "Maker Fee/Rebate" column → liquidity_role: MAKER
  - Market Maker: $0.50 (FEE, not rebate) in Penny — they PAY to provide liquidity
  - Priority Customer Tier 2+: ($0.47) REBATE in Penny — they GET PAID to provide
- "Taker Fee/Rebate" column → liquidity_role: TAKER
  - Market Maker: $0.35 (lower fee than maker side)
  - Priority Customer: ($0.31) to ($0.44) REBATE — they GET PAID to take
- Priority Customer vs Priority Customer (footnote 7): $0.00 both sides — no fees, no rebates

4-TIER STRUCTURE:
- Based on Total Customer ADV / Customer Total Consolidated Volume
- Tier 1: up to 0.15%, Tier 2: >0.15-0.40%, Tier 3: >0.40-0.70%, Tier 4: >0.70%
- NON-PRIORITY CUSTOMER FEES ARE FLAT ACROSS ALL TIERS
- Tiers only differentiate Priority Customer rebate levels
- For non-PC rows: extract as tier_level: 0 (base rate, single entry)

CONTRA-PARTY DEPENDENCIES:
- Footnote 8: Non-PC vs Priority Customer → Penny taker = $0.47 (not $0.35)
  → Extract with contra_origin_code: CUSTOMER, fee_value: 0.47
- Footnote 7: PC vs PC → $0.00 both sides
  → Extract with contra_origin_code: CUSTOMER, fee_value: 0.00
- Footnote 3: Affiliated entity discount for Non-Penny taker vs affiliated PC
  → Extract with tier_condition noting affiliated entity

COMPLEX ORDERS (Section 4):
- product_type: COMPLEX
- FLAT fees, NO maker/taker split → liquidity_role: NONE
  - Penny: $0.35 (non-PC), $0.00 (PC)
  - Non-Penny: $0.85 (non-PC), $0.00 (PC)
- Affiliated entity discount: $0.10 when vs affiliated PC
- Stock handling: $0.0010/share (max $50/trade) → fee_type: PER_SHARE
- Legs executing on regular book: use regular table Taker fees

AUCTION TYPES:
- Crossing (FAC, SOL, Block): auction_type: CROSSING
  - Originating + contra: $0.02 (non-PC), $0.00 (PC)
- PIM: auction_type: PIM
  - Originating: $0.20 (non-PC), $0.00 (PC)
  - Contra: $0.02
  - Response: $0.50 Penny, $1.10 Non-Penny
  - Break-up rebate: ($0.25) Penny, ($0.60) Non-Penny for PC
- QCC: auction_type: QCC — $0.20 (non-PC), $0.00 (PC)

SPY/QQQ/IWM (Footnote 6):
- MM Maker: $0.02 (dramatically lower than $0.50 standard)
- PC Taker: ($0.02) rebate (dramatically lower than standard)
- Extract as symbol-specific entries

ROUTING:
- exec_venue: ROUTED
- $0.60 Penny, $1.20 Non-Penny for all participants
"""
