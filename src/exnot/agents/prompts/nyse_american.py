"""NYSE American Options extraction prompt."""

PROMPT = """\
EXCHANGE: NYSE American Options
FORMAT: PDF (40 pages)

TERMINOLOGY MAPPING:
- "Customer" → origin_code: CUSTOMER
- "Professional Customer" → origin_code: PROFESSIONAL
- "NYSE American Options Market Maker" → origin_code: MARKET_MAKER
- "Non-NYSE American Options Market Maker" → origin_code: AWAY_MARKET_MAKER
- "Firm" → origin_code: FIRM
- "Broker-Dealer" → origin_code: BROKER_DEALER
- "DOMM" (Directed Order Market Maker) → origin_code: MARKET_MAKER (sub-type)
- "e-Specialist" / "Specialist" → origin_code: MARKET_MAKER (sub-type)
- "Firm Facilitation" → origin_code: FIRM, exec_venue: FLOOR, note facilitation

SECURITY CLASSES:
- "Penny" → penny_class: PENNY
- "Non-Penny" → penny_class: NON_PENNY
- NOTE: Penny/Non-Penny appears as ROW values in main table, not column headers
- Premium Products (SPY, AAPL, IWM, QQQ, TSLA, AMZN, NVDA, META, AMD, VXX) → note in fee_name
- BKX → listing_type: INDEX, symbol: BKX

TABLE STRUCTURE:
- Main Transaction Fees (pp 7-8): 5 columns — Participant | Penny/Non-Penny | Electronic Rate | Marketing Charge | Manual Rate
  Each participant has TWO rows (one Penny, one Non-Penny)
- MM Sliding Scale (pp 9-10): 4 tiers × (Non-Take Volume | Take Volume) with standard and Prepayment variants
  TWO versions: through June 30 2026 and effective July 1 2026
- ACE Program (p 14): 6 tiers × (Simple Credit | Complex Credit | Enhanced Simple | Enhanced Complex)
- CUBE (pp 16-19): separate tables for Single-Leg, Complex, AON
- QCC (p 15): simple 2-column table

HYBRID FEE MODEL:
- Main table: FLAT per-contract fee (no maker/taker for most participants) → liquidity_role: NONE
- MM Sliding Scale: HAS maker/taker → "Non-Take Volume" = MAKER, "Take Volume" = TAKER
- This is a HYBRID model — flat for most, maker/taker for MMs only

MARKET MAKER SLIDING SCALE:
- 4 tiers based on MM Electronic ADV as % of TCADV
- MARGINAL tiers (lower rate applies only to volume within that tier)
- Two versions with different thresholds (pre/post July 1 2026) — extract both with effective dates
- Prepayment Program variant: lower rates for members who prepay annual fees
- Extract standard and prepayment as separate tier groups

ACE PROGRAM (American Customer Engagement):
- 6 tiers (Base, 1-5) based on Customer Electronic ADV as % of TCADV
- Dual qualification: Customer-only ADV OR Total ADV (with 20% Customer minimum)
- Credits are RETROACTIVE to first contract
- Separate columns for Simple and Complex credits → product_type
- Enhanced credits for 1-year commitment
- is_rebate: true for all ACE entries

CUBE AUCTION:
- auction_type: CUBE
- Single-Leg CUBE: CUBE Order (Customer $0.00, Non-Customer $0.20), Contra Order ($0.05), RFR Response
- Complex CUBE: Contra $0.05 Penny / $0.07 Non-Penny, RFR Response $0.50 Penny / $1.05 Non-Penny
- AON CUBE: minimum 500 contracts, Contra $0.20
- Initiating Participant Credit: tiered by ACE tier
- auction_role: AGENCY (CUBE Order), CONTRA (Contra Order), RESPONDER (RFR Response), INITIATOR (credit)

QCC:
- auction_type: QCC
- C/P: $0.00, M/F/B: $0.20
- Floor Broker credits by composition

BOLD MECHANISM:
- auction_type: BOLD
- Customer Initiating: ($0.12) or ($0.13) if ACE-eligible
- Customer Responding: $0.00
- Non-Customer: standard transaction fees from main table

ELECTRONIC vs MANUAL:
- Main table has separate columns for Electronic and Manual rates
- exec_venue: ELECTRONIC or FLOOR
- Firm Facilitation (Manual only): $0.00

MARKETING CHARGES:
- MM liable when counterparty to electronic Customer trades
- Extract as separate fee entries with fee_name: "Marketing Charge"

DUAL EFFECTIVE DATES:
- MM Sliding Scale has two versions (through June 30 vs effective July 1)
- Extract both with appropriate effective_date values

NON-CUSTOMER COMPLEX SURCHARGE:
- $0.12 on Non-Customer Complex vs Customer Complex
- Reduced to $0.10 for ATP Holders at >= 0.20% TCADV
- Does NOT apply in CUBE Auctions

STRATEGY EXECUTION CAP:
- $1,000 (or $200 for high-volume) cap on reversals, box spreads, etc.
"""
