"""Base prompt shared across all exchanges — defines output schema and general rules."""

BASE_PROMPT = """\
OUTPUT SCHEMA — extract every fee row with these fields:

IDENTITY:
- fee_id: Exchange fee code if exists (e.g., "PY", "DcP"), else null
- fee_name: Human-readable name (e.g., "Customer Penny Maker Tier 1")

ORIGIN / CONTRA ORIGIN:
- origin_code: CUSTOMER | PROFESSIONAL | FIRM | BROKER_DEALER | MARKET_MAKER | AWAY_MARKET_MAKER
- contra_origin_code: Same values + ANY, or null if not contra-dependent

OCC Capacity Code Reference:
- C = CUSTOMER (Customer, Priority Customer, Public Customer, Retail)
- P = PROFESSIONAL (Professional, Professional Customer)
- F = FIRM (Firm, Firm Proprietary)
- B = BROKER_DEALER (Broker-Dealer, Non-Member BD, JBO)
- M = MARKET_MAKER (Market Maker, LMM, RMM, Specialist, DOMM)
- O = AWAY_MARKET_MAKER (Away Market Maker, Non-[Exchange] Market Maker, FarMM)

PRODUCT DIMENSIONS:
- product_type: SIMPLE | COMPLEX
- contra_product_type: SIMPLE | COMPLEX | null
- listing_type: EQUITY | ETF | INDEX
- penny_class: PENNY | NON_PENNY
- multi_listed: true | false | null
- symbol: Specific symbol if fee is symbol-specific (SPY, VIX, etc.), else null

EXECUTION TYPE (layered):
- exec_venue: ELECTRONIC | FLOOR | ROUTED
- liquidity_role: MAKER | TAKER | NONE
- auction_type: null, AIM, PRIME, CPRIME, PIM, PIXL, CUBE, PIP, COPIP, SAM, FAC, SOL, QCC, CQCC, QFO, CQFO, BOLD, FLEX, OPENING, C2C, CC2C, CROSSING (or null for regular orders)
- auction_role: null, AGENCY, CONTRA, RESPONDER, INITIATOR

FEE VALUE:
- fee_type: PER_CONTRACT | PER_NOTIONAL | PER_SHARE | MONTHLY | PERCENTAGE
- fee_value: USD amount. Negative = rebate.
- is_rebate: true if rebate/credit

TIERS:
- tier_level: 0 = base/default, 1+ = volume/quality tier, null if no tiers
- tier_condition: Human-readable condition (e.g., "ADAV >= 0.35% of OCV"), null for base

RULES:
- Rebates: negative fee_value, is_rebate=true. Fees: positive fee_value, is_rebate=false.
- Amounts in parentheses like ($0.25) are REBATES → fee_value: -0.25, is_rebate: true
- All per-contract amounts in USD per contract.
- Include ALL volume tiers — each tier is a separate fee entry with different tier_level and tier_condition.
- Base/default rates have tier_level=0 and tier_condition=null.
- Extract EVERY fee mentioned including ORF, routing, surcharges.
- Focus on OPTIONS transaction fees. Skip market data, connectivity, and membership fees unless per-contract.
- If a REFERENCE CONTEXT section is provided, use it for interpretation but do NOT extract fees from it.
"""
