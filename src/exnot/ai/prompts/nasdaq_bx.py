"""Nasdaq BX Options extraction prompt."""

PROMPT = """\
EXCHANGE: Nasdaq BX Options
FORMAT: HTML (same structure as NOM)

NOTE: Fee schedule URL may be stale. BX shares the Nasdaq family structure.
Use the same general approach as NOM with these BX-specific adjustments:

TERMINOLOGY MAPPING:
- Same as NOM: Customer (C), Professional (P), Broker-Dealer (B), Firm (F), Non-BX Market Maker (O), BX Market Maker (M)

SECURITY CLASSES:
- "Penny Symbols" → penny_class: PENNY
- "Non-Penny Symbols" → penny_class: NON_PENNY
- listing_type: EQUITY or ETF

TABLE STRUCTURE:
- Same as NOM: Add Liquidity / Remove Liquidity tables
- Tiers may differ in number and thresholds from NOM

MAKER/TAKER:
- "Add Liquidity" → MAKER
- "Remove Liquidity" → TAKER

Apply the same extraction logic as NOM. Look for footnote-based overrides,
symbol-specific rates, and cross-asset conditions.
"""
