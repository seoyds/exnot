"""Exchange-family-specific extraction hints for AI fee schedule parsing."""


def get_exchange_family(exchange_code: str) -> str:
    """Map exchange code to its family."""
    for family, info in EXCHANGE_FAMILY_HINTS.items():
        if exchange_code in info.get("families", []):
            return family
    return "OTHER"


def get_hints_for_exchange(exchange_code: str) -> dict:
    """Get extraction hints for a specific exchange."""
    family = get_exchange_family(exchange_code)
    return EXCHANGE_FAMILY_HINTS.get(family, EXCHANGE_FAMILY_HINTS["OTHER"])


EXCHANGE_FAMILY_HINTS = {
    "CBOE": {
        "families": ["CBOE_BZX", "CBOE_C1", "CBOE_C2", "CBOE_EDGX"],
        "terminology": {
            "Customer": "Priority Customer",
            "Non-Customer": "Professional + MM + Firm + BD + JBO",
        },
        "key_features": [
            "Fee codes (2-letter codes like PY, PC, PM, ZA)",
            "SPY-specific rates separate from other Penny",
            "RUT index license surcharges on Non-Customer only",
            "Complex order contra-party grids (Customer-vs-Customer, Customer-vs-NonCustomer)",
            "Cross-asset tiers (BZX Equities ADAV unlocks options rebates)",
            "Multi-condition AND/OR tier logic using ADAV, ADRV, ADV as % of OCV",
            "Opening trades often free",
            "Routing fees vary by destination exchange group",
        ],
        "prompt_addition": """CBOE-SPECIFIC INSTRUCTIONS:
- Extract ALL fee codes (2-letter codes like PY, PC, PM, ZA, etc.)
- SPY often has different rates than other Penny securities — capture as symbol="SPY"
- RUT has index license surcharges — capture as fee_type="SURCHARGE" with symbol="RUT"
- Complex orders: capture contra_party_type (CUSTOMER vs NON_CUSTOMER)
- Fee codes starting with Z are complex orders, R are routed, P are penny, N are non-penny, B are RUT, O are opening
- Volume tiers reference ADAV/ADRV/ADV as % of OCV — capture exact thresholds
- Cross-asset tiers reference BZX Equities volume — capture in tier_conditions
- Opening trades (codes OO, OC, BO, GO) are typically free ($0.00)""",
    },
    "NASDAQ": {
        "families": ["NASDAQ_ISE", "NASDAQ_NOM", "NASDAQ_PHLX", "NASDAQ_GEMX",
                      "NASDAQ_MRX", "NASDAQ_NTX"],
        "terminology": {
            "Priority Customer": "Public Customer (< 390 orders/day)",
            "Professional Customer": "Professional (>= 390 orders/day)",
            "FarMM / Non-Nasdaq ISE MM": "Away Market Maker",
        },
        "key_features": [
            "MM Plus tiers based on NBBO time percentage (not volume)",
            "Priority Customer Complex tiers (up to 10 levels)",
            "Select Symbols = Penny, Non-Select Symbols = Non-Penny",
            "Linked symbol rebate programs (SPY-QQQ, SPY-IWM)",
            "PIM volume discounts (retroactive)",
            "Crossing/Solicitation rebate stacking",
            "QCC rebates with tier enhancements",
        ],
        "prompt_addition": """NASDAQ-SPECIFIC INSTRUCTIONS:
- "Select Symbols" = PENNY, "Non-Select Symbols" = NON_PENNY
- "Priority Customer" = CUSTOMER, "Professional Customer" = PROFESSIONAL
- "Non-Nasdaq ISE Market Maker" / "FarMM" = AWAY_MARKET_MAKER
- MM Plus tiers are based on NBBO time % — use metric="NBBO_PCT" in tier_conditions
- Priority Customer Complex tiers (up to 10) are based on % of Customer Total Consolidated Volume
- Capture PIM orders as order_type="PIM", Crossing/FAC/SOL as order_type="CROSSING"
- QCC and Solicitation fees may stack — note stacking in conditions
- When fees differ based on contra-party, set contra_party_type
- Section 3 = Regular Orders, Section 4 = Complex Orders, Section 5 = Index Options, Section 6 = Other""",
    },
    "MIAX": {
        "families": ["MIAX_OPTIONS", "MIAX_PEARL", "MIAX_EMERALD", "MIAX_SAPPHIRE"],
        "terminology": {
            "Priority Customer": "Public Customer",
            "PRIME": "Price Improvement Mechanism (auction)",
            "cPRIME": "Complex PRIME auction",
        },
        "key_features": [
            "Liquidity Indicator codes",
            "PRIME and cPRIME auction mechanisms",
            "Priority Customer tiered rebates (volume-based)",
        ],
        "prompt_addition": """MIAX-SPECIFIC INSTRUCTIONS:
- "Priority Customer" = CUSTOMER
- PRIME auction orders = order_type="PIM", cPRIME = order_type="PIM" with order_type note
- Capture Liquidity Indicator codes as fee_code
- Volume tiers use ADV thresholds as % of national Customer volume
- Capture PRIME/cPRIME fees separately from regular maker/taker""",
    },
    "NYSE": {
        "families": ["NYSE_ARCA", "NYSE_AMERICAN"],
        "terminology": {
            "Customer": "Public Customer",
            "Firm": "Firm / Broker-Dealer",
        },
        "key_features": [
            "Tier-based maker/taker with absolute contract thresholds",
            "Customer Penny Pilot tiers",
            "Step-up credits",
        ],
        "prompt_addition": """NYSE-SPECIFIC INSTRUCTIONS:
- Volume tiers use absolute monthly contract counts (not percentages)
- Capture step-up credits as separate fee entries with conditions
- Customer Penny Pilot tiers are common — capture all tiers
- Both NYSE Arca and NYSE American are PDF-based fee schedules""",
    },
    "OTHER": {
        "families": ["BOX_OPTIONS", "MEMX_OPTIONS"],
        "key_features": [
            "BOX: PIP auction, simpler structure",
            "MEMX: Composite fee codes [Action][Capacity][Tier][SecurityClass]",
        ],
        "prompt_addition": """EXCHANGE-SPECIFIC INSTRUCTIONS:
- Extract ALL fee codes exactly as shown in the schedule
- For MEMX: fee codes follow pattern [Action][Capacity][Tier?][SecurityClass] e.g. Dp1P
- For BOX: PIP (Price Improvement Period) = order_type="PIM"
- Capture all volume tiers with their exact conditions""",
    },
}
