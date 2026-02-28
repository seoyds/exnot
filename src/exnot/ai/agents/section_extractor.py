"""Section extractor agent — EXPENSIVE tier.

Extracts fee data from one section (or the full document for small docs).
This is the core value task — it does the actual fee extraction.
"""

from __future__ import annotations

from pydantic_ai import Agent, ModelRetry, RunContext

from exnot.ai.deps import ExtractionDeps
from exnot.ai.types import SectionExtractionResult

# Domain rules shared across all extraction prompts
EXTRACTION_RULES = """\
RULES:
- Rebates: negative amounts, is_rebate=true. Fees: positive amounts, is_rebate=false.
- All per-contract amounts in USD per contract.
- Participant mapping:
  "Public Customer"/"Priority Customer"/"Retail" → CUSTOMER
  "Professional"/"Professional Customer" → PROFESSIONAL
  "Market Maker"/"Specialist"/"LMM"/"DPM"/"PMM"/"CMM" → MARKET_MAKER
  "Away Market Maker"/"Non-Member MM"/"FarMM" → AWAY_MARKET_MAKER
  "Firm"/"Proprietary" → FIRM
  "Broker-Dealer"/"BD"/"JBO" → BROKER_DEALER
  Grouped non-customer → NON_CUSTOMER
- When a fee depends on the contra-party (e.g., "Customer vs Non-Customer"), set contra_party_type.
- Include ALL volume tiers — each tier is a separate fee entry with the same fee_code but different tier_number and tier_conditions.
- Base/default rates have tier_number=0 and tier_conditions=null.
- For tiered entries, tier_group links related tiers.
- Extract EVERY fee mentioned including ORF, routing, surcharges.
- Focus on OPTIONS transaction fees. Skip market data, connectivity, and membership fees unless per-contract.
"""

section_extractor_agent = Agent[ExtractionDeps, SectionExtractionResult](
    "test",
    deps_type=ExtractionDeps,
    output_type=SectionExtractionResult,
    instructions=(
        "You are a financial data extraction specialist for US options exchange fee schedules.\n"
        "Analyze the provided section and extract ALL fee and rebate amounts.\n\n"
        f"{EXTRACTION_RULES}\n"
        "If a REFERENCE CONTEXT section is provided, use it for interpretation "
        "(definitions, footnotes, glossary) but do NOT extract fees from it.\n"
    ),
    retries=2,
)


@section_extractor_agent.output_validator
async def validate_extraction(
    ctx: RunContext[ExtractionDeps], output: SectionExtractionResult
) -> SectionExtractionResult:
    """Validate extracted fees for sign/rebate consistency."""
    issues: list[str] = []

    for i, fee in enumerate(output.fees):
        # Check rebate/sign consistency
        if fee.is_rebate and fee.amount > 0:
            issues.append(
                f"Fee[{i}]: is_rebate=true but amount={fee.amount} is positive. "
                "Rebates should have negative amounts."
            )
        elif not fee.is_rebate and fee.amount < 0:
            issues.append(
                f"Fee[{i}]: is_rebate=false but amount={fee.amount} is negative. "
                "If this is a rebate, set is_rebate=true."
            )

    if issues:
        raise ModelRetry(
            "Sign/rebate inconsistencies found. Fix these issues:\n"
            + "\n".join(issues)
        )

    return output
