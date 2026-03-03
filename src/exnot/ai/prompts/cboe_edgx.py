"""Cboe EDGX Options Exchange extraction prompt."""

PROMPT = """\
EXCHANGE: Cboe EDGX Options Exchange
FORMAT: HTML with fee code reference table

TERMINOLOGY MAPPING:
- "Customer" → origin_code: CUSTOMER
- "Professional" → origin_code: PROFESSIONAL
- "Market Maker" → origin_code: MARKET_MAKER
- "Away Market Maker" → origin_code: AWAY_MARKET_MAKER
- "Broker Dealer" → origin_code: BROKER_DEALER
- "Firm" → origin_code: FIRM
- "Joint Back Office" (JBO) → origin_code: BROKER_DEALER
- "Non-Customer" = PROFESSIONAL, FIRM, BROKER_DEALER, MARKET_MAKER, AWAY_MARKET_MAKER
- "Non-Customer, Non-Professional" = F, B, M, O

SECURITY CLASSES:
- "Penny Program Securities" → penny_class: PENNY
- "Non-Penny Program Securities" → penny_class: NON_PENNY
- listing_type: EQUITY or ETF (EDGX has no index products)

FEE CODES:
- 2-character codes with prefixes:
  - P_ = Penny simple, N_ = Non-Penny simple
  - Z_ = Complex, R_ = Routed, O_ = Opening
  - B_ = AIM mechanism, S_ = SAM mechanism, Q_ = QCC
  - CA = Customer contra Non-Customer adds liquidity
  - TP/TN = Customer-to-Customer adds liquidity
  - CC = AIM Customer-to-Customer Immediate Cross
  - E_ = Equity leg codes (firm-specific: EF, EL, EP, EQ, ES)

TABLE STRUCTURE:
- Standard Rates: participant rows × (Penny Add | Penny Remove | Non-Penny Add | Non-Penny Remove)
- "Add" = MAKER, "Remove" = TAKER
- Parenthetical amounts = rebates

COMPLEX ORDERS:
- Z-prefix codes with origin/contra grid:
  - When agency is Customer: ZC (CUSTOMER vs CUSTOMER = free), ZM/ZN (CUSTOMER vs MARKET_MAKER), ZT/ZR (CUSTOMER vs non-MM non-CUSTOMER)
  - When agency is Non-Customer contra Customer: ZA/ZB (rebates)
  - Add/Remove: ZF/ZH (add), ZG/ZJ (remove)
- product_type: COMPLEX, extract contra_origin_code from table context

AIM (Automated Improvement Mechanism):
- auction_type: AIM
- B-prefix codes: BA (Agency Non-Customer), BB (Contra Penny), BC (Agency Customer Penny), BD/BE (Response), BF (Contra Non-Penny), BG (Agency Customer Non-Penny)
- auction_role: AGENCY for BA/BC/BG, CONTRA for BB/BF, RESPONDER for BD/BE
- CC = AIM Customer-to-Customer Immediate Cross → free
- Break-up credits: extract as separate entries with is_rebate: true

SAM (Solicitation Auction Mechanism):
- auction_type: SAM
- S-prefix codes: SA-SH
- Same role structure as AIM

QCC:
- auction_type: QCC, Q-prefix codes (QA, QC, QM, QN, QO, QP)
- Customer and Professional: free
- Non-Customer Non-Professional: $0.20
- Volume rebate tiers based on absolute monthly contract volume

TIERS:
- Customer Simple: 6 tiers based on ADV % of OCV
- Customer Complex Penny: 5 tiers, Non-Penny: 4 tiers
- Market Maker: 5 tiers based on ADV % of OCV
- AIM Supplemental: 3 tiers based on "Interaction Rate"
- QCC Rebate: 3 tiers based on absolute monthly contracts

UNIQUE FEATURES:
- Customers receive rebates on BOTH sides (maker and taker)
- Marketing Fee codes (P, N, X) — extract if present
- AIM Interaction Rate tiers are unique to EDGX
- Break-up credits for both AIM and SAM
"""
