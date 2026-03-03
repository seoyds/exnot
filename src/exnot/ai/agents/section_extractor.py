"""Section extractor agent — EXPENSIVE tier.

Extracts fee data from one section (or the full document for small docs).
This is the core value task — it does the actual fee extraction.
"""

from __future__ import annotations

from pydantic_ai import Agent, RunContext, ToolOutput

from exnot.ai.deps import ExtractionDeps
from exnot.ai.types import SectionExtractionResult

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


@section_extractor_agent.output_validator
async def validate_extraction(
    ctx: RunContext[ExtractionDeps], output: SectionExtractionResult
) -> SectionExtractionResult:
    """Validate and auto-correct sign/rebate consistency."""
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

    return output
