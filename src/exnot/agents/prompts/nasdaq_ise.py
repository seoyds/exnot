"""Nasdaq ISE extraction prompt."""

PROMPT = """\
EXCHANGE: Nasdaq ISE (International Securities Exchange)
FORMAT: HTML with multiple numbered sections

TERMINOLOGY MAPPING:
- "Priority Customer" → origin_code: CUSTOMER (not a broker/dealer AND <= 390 orders/day average)
- "Professional Customer" → origin_code: PROFESSIONAL (not a broker/dealer AND > 390 orders/day)
- "Market Maker" (ISE-registered) → origin_code: MARKET_MAKER
- "Non-Nasdaq ISE Market Maker" / "FarMM" → origin_code: AWAY_MARKET_MAKER
- "Firm Proprietary / Broker-Dealer" → origin_code: FIRM (for Firm), BROKER_DEALER (for Broker-Dealer)
  NOTE: ISE combines these in one row. Extract as origin_code: FIRM for the combined entry, or split if separate rates given.
- "Non-Priority Customers" = MARKET_MAKER, AWAY_MARKET_MAKER, FIRM, BROKER_DEALER, PROFESSIONAL

SECURITY CLASSES:
- "Select Symbols" = Penny Interval Program → penny_class: PENNY
- "Non-Select Symbols" = NOT in Penny Interval → penny_class: NON_PENNY
- NDX, XND, MNX → listing_type: INDEX, symbol as given
- All others → listing_type: EQUITY or ETF

TABLE STRUCTURE:
- Section 3 (Regular Orders): rows = participant types, columns = Maker Rebate/Fee | Taker Fee | Crossing Fee (ex PIM) | PIM Fee | Response to Crossing | Response to PIM | FAC/SOL Break-up Rebate | PIM Break-up Rebate
- Separate tables for Select Symbols and Non-Select Symbols
- Section 4 (Complex Orders): separate sub-tables for Priority Customer rebate tiers, maker/taker grid, crossing grid
- Section 5 (Index Options): simpler flat-fee tables
- Section 6 (Other): QCC, SOL, PIM/FAC, FLEX, Route-Out

MAKER/TAKER:
- "Maker Rebate/Fee" → liquidity_role: MAKER
- "Taker Fee" → liquidity_role: TAKER
- Priority Customer Select: Maker = $0.00, Taker = fee
- Priority Customer Non-Select: Maker = rebate, Taker = $0.00
- Rebates in parentheses

COMPLEX ORDERS (Section 4):
- product_type: COMPLEX
- Priority Customer Complex Rebate: 10 tiers based on % of Customer Total Consolidated Volume
- Maker/Taker grid has a "vs. Priority Customer" column — extract contra_origin_code: CUSTOMER
- $0.12 surcharge when Non-Priority takes vs Priority Customer in Complex Book

MARKET MAKER PLUS TIERS:
- Based on % time at NBBO (quoting quality, not volume)
- Different tier sets for: general Select, SPY/QQQ/IWM, AMZN/META/NVDA, Non-Select
- tier_condition: "NBBO time >= X%"
- Cross-symbol qualification: achieving tier in 2 of 3 linked symbols qualifies the third
- "Linked Maker Rebate" for SPY/QQQ/IWM Tier 2+ — extract as separate entries

AUCTION TYPES:
- FAC (Facilitation): auction_type: FAC
- SOL (Solicitation): auction_type: SOL
- PIM (Price Improvement Mechanism): auction_type: PIM
- QCC: auction_type: QCC
- FLEX: note in fee_name
- Block Order Mechanism: auction_type: CROSSING
- Exposure Auction: originating = MAKER rates, contra = TAKER rates

AUCTION ROLES:
- "Fee for Crossing Orders" → auction_role: AGENCY + CONTRA (both sides)
- "Fee for Responses to Crossing Orders" → auction_role: RESPONDER
- "Break-up Rebate" → separate entry with is_rebate: true

CONTRA-PARTY DEPENDENCIES (embedded in footnotes):
- Footnote (6): Non-Select Tier 3 changes from rebate to fee when contra is Priority Customer
- Footnote (3): Taker fee changes based on contra being Priority Customer
- Footnote (8): $0.12 surcharge on Non-Priority vs Priority Customer in Complex Book
- Extract these as separate fee entries with contra_origin_code: CUSTOMER

ROUTING:
- exec_venue: ROUTED
- Flat $0.60 Select / $1.20 Non-Select for all participants
- liquidity_role: NONE

SPECIAL RULES:
- NDX/XND/MNX excluded from complex order rebates
- Complex XND orders use Section 5 (Index) fees instead of Section 4
- Stock-option orders: $0.0010/share stock handling fee (capped $50/trade) → fee_type: PER_SHARE
- "Net zero" complex orders (within $0.01 debit/credit) excluded from rebates
"""
