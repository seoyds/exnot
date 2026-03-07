"""MIAX Options Exchange extraction prompt."""

PROMPT = """\
EXCHANGE: MIAX Options Exchange
FORMAT: PDF (41 pages, linked from landing page)

TERMINOLOGY MAPPING:
- "Priority Customer" → origin_code: CUSTOMER
- "Public Customer that is Not a Priority Customer" → origin_code: PROFESSIONAL
- "MIAX Market Maker" (includes RMM, LMM, PLMM, DLMM, DPLMM) → origin_code: MARKET_MAKER
- "Non-MIAX Market Maker" → origin_code: AWAY_MARKET_MAKER
- "Non-Member Broker-Dealer" → origin_code: BROKER_DEALER
- "Firm" → origin_code: FIRM

SECURITY CLASSES:
- "Penny Classes" → penny_class: PENNY
- "Non-Penny Classes" → penny_class: NON_PENNY
- "Select Symbols" (56 specific symbols including SPY, QQQ, IWM, AAPL, etc.) → note in fee_name
- listing_type: EQUITY or ETF

TABLE STRUCTURE — MULTIPLE FORMATS:
1. Market Maker Sliding Scale (pp 4-5): rows = tiers, columns = Simple(Penny Maker|Taker, Non-Penny Maker|Taker) | Complex(Penny, Non-Penny) | Complex Surcharge
   TWO versions: "In PC Rebate Tier 3+" and "Not In Tier 3+"
2. Other Participant Fees (pp 6-7): rows = participants, columns = Penny | Non-Penny | Surcharge
   FLAT fees for simple AND complex combined
3. Priority Customer Rebate Program (p 8): 4 tiers × 5 credit columns
4. PRIME/cPRIME tables (pp 12-13): rows = participants, columns = Agency | Contra | Responder(P/NP) | Break-up(P/NP)
5. QCC/cQCC tables (pp 14-15): rows = participants, columns = Initiator | Contra | Rebate by contra origin

MARKET MAKER SLIDING SCALE:
- 5 tiers based on % national MM volume in multiply-listed classes
- TWO tables: one for members in PC Rebate Tier 3+, one for those not
- This cross-references creates a dependency: MM fees depend on BOTH MM volume tier AND PC volume tier
- For extraction: create entries for both variants, note the cross-reference in tier_condition
- Simple orders: Maker/Taker split → liquidity_role: MAKER or TAKER
- Complex orders: single fee (no maker/taker) → liquidity_role: NONE
- Complex surcharge: $0.12 when contra is Priority Customer complex → separate entry with contra_origin_code: CUSTOMER

OTHER PARTICIPANTS (non-MM):
- FLAT fee covers both simple and complex → product_type: SIMPLE and COMPLEX (create entry for each)
- No maker/taker split → liquidity_role: NONE
- Footnote-conditional discounts at PC Rebate Tier 3+/4 → extract as separate tiered entries

PRIORITY CUSTOMER REBATE PROGRAM:
- 4 tiers based on % National Customer Volume
- 5 columns: Simple non-Select | Simple Select | PRIME Agency | cPRIME Agency | Complex
- is_rebate: true for all entries
- "Select Symbols" column → note specific symbol list in fee_name

PROFESSIONAL REBATE PROGRAM:
- 3 tiers based on % volume increase above baseline
- Applies to P, O, B, F origins — liquidity-adding only
- Separate rates for Simple and Complex
- Per-tier (NOT retroactive)

PRIME AUCTION:
- auction_type: PRIME
- Roles: AGENCY, CONTRA, RESPONDER
- Break-up credits with percentage-based adjustments (0-20%, 20-40%, etc.)
- Extract break-up entries with tier_condition: "Break-up >= X%"
- Enhanced break-up at >40%: separate entry

cPRIME AUCTION:
- auction_type: CPRIME
- Same role structure as PRIME
- Per contract per leg
- cPRIME Break-up Table: 10 tiers (0-10% through 90-100%)

QCC / cQCC:
- auction_type: QCC or CQCC
- Minimum 1,000 contracts
- Rebates vary by contra origin:
  - contra PC → one rebate amount
  - contra Public Customer (not PC) → different amount
  - contra all others → different amount
- Extract 3 entries per origin with different contra_origin_code values

C2C / cC2C:
- auction_type: C2C or CC2C
- $0.00 per contract

COMPLEX SURCHARGE:
- $0.12 per contract on non-PC trading against PC complex order
- Applies on Strategy Book and complex auctions (excluding cPRIME)
- contra_origin_code: CUSTOMER

ROUTING:
- exec_venue: ROUTED
- Destination-specific fees (different amounts per away exchange)
- Split by origin type and Penny/Non-Penny

MARKETING FEE:
- $0.25/contract Penny, $0.70/contract Non-Penny
- Paid by Market Makers into a pool controlled by LMM/PLMM
- Extract as fee_type: PER_CONTRACT with fee_name: "Marketing Fee"
"""
