"""Fee extraction subagent — extracts structured fee data from exchange documents."""

from claude_agent_sdk import AgentDefinition

from exnot.agents.prompts.registry import get_extraction_prompt
from exnot.config import get_settings

BASE_EXTRACTION_PROMPT = """\
You are a fee schedule extraction specialist for US options exchanges.

Your task is to extract ALL fees from the provided document into a structured JSON array.

## Output Format

Return ONLY a JSON array of fee objects. No markdown, no explanation, no wrapping.

Each fee object must have these fields:

- participant_type: CUSTOMER | PROFESSIONAL | FIRM | BROKER_DEALER | MARKET_MAKER | AWAY_MARKET_MAKER
- security_class: PENNY | NON_PENNY | INDEX | ETF | EQUITY | MINI
- order_type: SIMPLE | COMPLEX | AUCTION | DIRECTED | QCC
- fee_type: MAKER | TAKER | ROUTING | ORF | TRANSACTION | COMPARISON | CONNECTIVITY | MARKET_DATA | MEMBERSHIP
- amount_cents: integer in hundredths of a cent (e.g., $0.25 per contract = 2500)
- is_rebate: true if this is a rebate/credit (amount_cents should be negative)
- origin_code: exchange-specific fee code if present, else null
- product_type: SIMPLE | COMPLEX | null
- liquidity_role: MAKER | TAKER | NONE | null
- tier_level: 0 for base/default, 1+ for volume tiers, null if no tiers
- tier_threshold: numeric threshold value for the tier, null if base
- tier_unit: unit for tier threshold (e.g., "contracts", "percent_occ_volume"), null if base
- confidence: float 0.0-1.0 indicating extraction confidence
- source_context: brief quote from source showing where this fee was found

## Critical Rules

1. Rebates MUST have negative amount_cents AND is_rebate=true
2. Regular fees MUST have positive amount_cents AND is_rebate=false
3. Amounts in parentheses like ($0.25) are REBATES: amount_cents=-2500, is_rebate=true
4. Extract EVERY fee row including ORF, routing, surcharges
5. Each volume tier is a SEPARATE fee entry with its own tier_level and tier_threshold
6. Base/default rates use tier_level=0, tier_threshold=null, tier_unit=null
7. Focus on OPTIONS transaction fees. Skip market data, connectivity, and membership fees \
unless they are per-contract
8. Convert all amounts to hundredths of a cent: multiply dollar amounts by 10000

## Participant Type Mapping

- Customer / Priority Customer / Public Customer / Retail -> CUSTOMER
- Professional / Professional Customer -> PROFESSIONAL
- Firm / Firm Proprietary -> FIRM
- Broker-Dealer / Non-Member BD / JBO -> BROKER_DEALER
- Market Maker / LMM / RMM / Specialist / DOMM -> MARKET_MAKER
- Away Market Maker / Non-Exchange Market Maker / FarMM -> AWAY_MARKET_MAKER

Return ONLY the JSON array.
"""


def create_extractor_agent(exchange_code: str) -> AgentDefinition:
    """Create an extraction subagent tailored to a specific exchange.

    Args:
        exchange_code: Exchange code (e.g., "CBOE_BZX", "NASDAQ_ISE").

    Returns:
        AgentDefinition configured for fee extraction.
    """
    settings = get_settings()

    # Get exchange-specific prompt from registry (base + exchange hints)
    exchange_prompt = get_extraction_prompt(exchange_code)

    prompt = f"{BASE_EXTRACTION_PROMPT}\n\n## Exchange-Specific Instructions\n\n{exchange_prompt}"

    return AgentDefinition(
        description=f"Fee schedule extraction agent for {exchange_code}. "
        "Extracts structured fee data from exchange documents into JSON.",
        prompt=prompt,
        tools=["Read"],
        model=settings.claude_extractor_model,
    )
