"""Cboe Options Exchange (C1) extraction prompt."""

PROMPT = """\
EXCHANGE: Cboe Options Exchange (C1)
FORMAT: CSV (3 columns: Fee Code | Description | Amount) — NO header row

TERMINOLOGY MAPPING:
- "Customer" → origin_code: CUSTOMER
- "Professional Customer" / "ProCustomer" → origin_code: PROFESSIONAL
- "Market-Maker" / "Market Maker" / "MarketMaker" → origin_code: MARKET_MAKER
- "Away Market-Maker" → origin_code: AWAY_MARKET_MAKER
- "Firm" → origin_code: FIRM
- "Broker-Dealer" → origin_code: BROKER_DEALER
- "Non-Customer, Non-Market-Maker, Non-Firm" → origin_code: BROKER_DEALER
- "Non-Customer, Non-Market-Maker, Non-Firm, Non-ProCustomer" → origin_code: BROKER_DEALER
- Note: hyphenation is inconsistent ("Market-Maker" vs "Market Maker")

SECURITY CLASSES — PRODUCT-SPECIFIC:
- "Penny" → penny_class: PENNY, listing_type: EQUITY/ETF
- "Non-Penny" → penny_class: NON_PENNY, listing_type: EQUITY/ETF
- "ETF" / "Equity" → listing_type: ETF or EQUITY, penny_class based on context
- "SPX" / "SPESG" → listing_type: INDEX, symbol: SPX, penny_class: NON_PENNY
- "VIX" → listing_type: INDEX, symbol: VIX, penny_class: NON_PENNY
- "RUT" / "MRUT" → listing_type: INDEX, symbol: RUT/MRUT
- "XSP" → listing_type: INDEX, symbol: XSP
- "OEX" / "XEO" → listing_type: INDEX, symbol: OEX/XEO
- "DJX" → listing_type: INDEX, symbol: DJX
- "MXEA" / "MXEF" → listing_type: INDEX, symbol: MXEA/MXEF
- "MGTN" → listing_type: INDEX, symbol: MGTN
- "NANOS" → listing_type: INDEX, symbol: NANOS
- "SPEQX" → listing_type: INDEX, symbol: SPEQX
- "CBTX" / "MBTX" → listing_type: INDEX, symbol: CBTX/MBTX
- "Sector Indexes" → listing_type: INDEX

FEE CODES:
- 123 unique 2-character codes. The fee_id IS the fee code.
- Description field is a comma-separated attribute string — decompose into schema fields
- Amount column: negative = rebate, positive = fee. Formats vary: 0.45, .45, 0, -0.30

PARSING THE DESCRIPTION FIELD:
- Split by comma. Each token maps to a schema field:
  - Participant type token → origin_code
  - "Penny"/"Non-Penny"/"ETF"/"Equity" → penny_class + listing_type
  - Product symbol (SPX, VIX, etc.) → symbol + listing_type: INDEX
  - "Adds liquidity"/"Adding Liquidity" → liquidity_role: MAKER
  - "Removes liquidity"/"Removing Liquidity" → liquidity_role: TAKER
  - "Manual" → exec_venue: FLOOR
  - "Electronic" → exec_venue: ELECTRONIC
  - "Contra Customer"/"Contra Non-Customer" → contra_origin_code
  - "Complex" → product_type: COMPLEX
  - "AIM Agency"/"AIM Responder"/"AIM Contra" → auction_type: AIM + auction_role
  - "QCC" → auction_type: QCC
  - "Routed" → exec_venue: ROUTED
  - "Terminal" → exec_venue: ROUTED (terminal-originated)
  - "Flex"/"Flex Micro" → note in fee_name
  - "Premium < $1.00" / "Premium >= $1.00" → tier_condition (premium-based tier)
  - ">= 100 contracts" / "< 100 contracts" → tier_condition (size-based tier)
  - ">= 10 contracts" / "< 10 contracts" → tier_condition
  - ">= 5000 Contracts" → tier_condition
  - "Facilitation" → auction_type: FAC
  - "Compression" / "Reversal" / "Strategy" → note in fee_name, fee_value typically 0

PREMIUM-BASED TIERS (unique to C1):
- SPX: 2 tiers — Premium < $1.00 vs >= $1.00
- VIX Simple: 4 tiers — $0.00-$0.10, $0.11-$0.99, $1.00-$1.99, >= $2.00
- VIX Complex: 4 tiers — same premium brackets, lower fees
- Extract as tier_level: 0-3, tier_condition: "Premium [range]"

CONTRA-PARTY PRICING:
- XSP and MGTN have contra-party-dependent fees
- "Contra Customer" → contra_origin_code: CUSTOMER
- "Contra Non-Customer" → contra_origin_code: ANY (meaning PROFESSIONAL/FIRM/BROKER_DEALER/MARKET_MAKER/AWAY_MARKET_MAKER)

EXECUTION VENUES:
- If "Electronic" in description → exec_venue: ELECTRONIC
- If "Manual" in description → exec_venue: FLOOR
- If "Routed" in description → exec_venue: ROUTED
- If none specified → exec_venue: ELECTRONIC (default for C1)

SPECIAL RULES:
- Facilitation (FF), Compression (SC, ST), Reversal (RV), Strategy (FS) are all $0.00
- Equity leg codes (EF, EL, EP, EQ, ES) are firm-specific — extract with fee_name noting the firm
- NANOS options have their own codes (NM, NN, NO)
- No volume-based tiers in the CSV — volume incentive programs are in supplementary documents
"""
