"""Fee validator agent — MEDIUM tier.

Validates extraction completeness and quality, replacing the heuristic
_compute_confidence and _identify_issues functions.
"""

from __future__ import annotations

from pydantic_ai import Agent, ToolOutput

from exnot.ai.deps import ExtractionDeps
from exnot.ai.types import ValidationResult

fee_validator_agent = Agent[ExtractionDeps, ValidationResult](
    "test",
    deps_type=ExtractionDeps,
    output_type=ToolOutput(ValidationResult, name="return_validation"),
    instructions=(
        "You validate extracted fee data from US options exchange fee schedules.\n"
        "Check for completeness and correctness:\n\n"
        "REQUIRED coverage for a typical exchange:\n"
        "- CUSTOMER fees (most exchanges have these)\n"
        "- MARKET_MAKER fees\n"
        "- MAKER and TAKER fee types\n"
        "- PENNY and/or NON_PENNY security classes\n"
        "- At least 10-20 fee entries for a typical exchange\n\n"
        "Check for:\n"
        "- Missing participant types that should be present\n"
        "- Missing fee types (at minimum MAKER + TAKER)\n"
        "- Amount outliers (> $3.00/contract is unusual)\n"
        "- Incomplete tier groups (tier_number gaps)\n"
        "- Sign/rebate inconsistencies\n\n"
        "Set confidence 0.0-1.0 based on coverage completeness.\n"
        "Set is_valid=true if confidence >= 0.8.\n"
    ),
    retries=1,
)
