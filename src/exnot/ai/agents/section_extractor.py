"""Section extractor agent — EXPENSIVE tier.

Extracts fee data from one section (or the full document for small docs).
This is the core value task — it does the actual fee extraction.
"""

from __future__ import annotations

from collections import defaultdict

from pydantic_ai import Agent, ModelRetry, RunContext, ToolOutput

from exnot.ai.deps import ExtractionDeps
from exnot.ai.types import ExtractedFee, SectionExtractionResult

section_extractor_agent = Agent[ExtractionDeps, SectionExtractionResult](
    "test",
    deps_type=ExtractionDeps,
    output_type=ToolOutput(SectionExtractionResult, name="return_extraction"),
    instructions=(
        "You are a financial data extraction specialist for US options exchange fee schedules.\n"
        "Analyze the provided section and extract ALL fee and rebate amounts.\n"
        "Follow the extraction instructions provided in the user message.\n"
        "If a REFERENCE CONTEXT section is provided, use it for interpretation "
        "(definitions, footnotes, glossary) but do NOT extract fees from it.\n"
    ),
    retries=4,
)


def _fee_dimension_key(fee: ExtractedFee) -> tuple:
    """Build a key from fee dimensions (excluding tier and amount)."""
    return (
        fee.origin_code or fee.participant_type,
        fee.penny_class or fee.security_class,
        fee.product_type or fee.order_type,
        fee.liquidity_role or fee.fee_type,
        fee.exec_venue,
        fee.symbol,
    )


@section_extractor_agent.output_validator
async def validate_extraction(
    ctx: RunContext[ExtractionDeps], output: SectionExtractionResult
) -> SectionExtractionResult:
    """Validate and auto-correct sign/rebate consistency and tier classification."""
    for fee in output.fees:
        # V3 uses fee_value, V2 uses amount
        if fee.fee_value is not None:
            if fee.is_rebate and fee.fee_value > 0:
                fee.fee_value = -fee.fee_value
            elif not fee.is_rebate and fee.fee_value < 0:
                fee.is_rebate = True
        elif fee.amount is not None:
            if fee.is_rebate and fee.amount > 0:
                fee.amount = -fee.amount
            elif not fee.is_rebate and fee.amount < 0:
                fee.is_rebate = True

    # Detect duplicate dimensions with different amounts but missing tier info
    groups: dict[tuple, list[ExtractedFee]] = defaultdict(list)
    for fee in output.fees:
        groups[_fee_dimension_key(fee)].append(fee)

    missing_tiers = []
    for key, fees in groups.items():
        if len(fees) < 2:
            continue
        amounts = {fee.fee_value or fee.amount for fee in fees}
        if len(amounts) < 2:
            continue
        # Multiple fees with same dimensions but different amounts — should be tiered
        untiereds = [f for f in fees if f.tier_level is None]
        if untiereds:
            codes = [f.fee_id or f.fee_code or "?" for f in fees]
            missing_tiers.append(f"{key[0]}/{key[1]}/{key[3]} codes={codes}")

    if missing_tiers:
        raise ModelRetry(
            f"Found fees with identical dimensions but different amounts and NO tier_level set: "
            f"{missing_tiers}. These are tiered fees. "
            f"Set tier_level=0 for the base rate and tier_level=1+ for volume tiers. "
            f"Set tier_condition to the human-readable qualification criteria for each tier."
        )

    return output
