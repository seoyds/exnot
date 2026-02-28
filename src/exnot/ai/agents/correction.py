"""Correction agent — EXPENSIVE tier, budget-gated.

Receives the previous extraction + specific issues + document context,
returns targeted fixes. Replaces the SELF_QUESTION_PROMPT loop.
"""

from __future__ import annotations

from pydantic_ai import Agent

from exnot.ai.deps import ExtractionDeps
from exnot.ai.types import CorrectionResult

correction_agent = Agent[ExtractionDeps, CorrectionResult](
    "test",
    deps_type=ExtractionDeps,
    output_type=CorrectionResult,
    instructions=(
        "You correct and supplement fee data extracted from US options exchange fee schedules.\n\n"
        "You will receive:\n"
        "1. Previously extracted fees\n"
        "2. Specific issues identified by a validator\n"
        "3. The source document text/tables\n\n"
        "Your task:\n"
        "- Fix the specific issues identified\n"
        "- Add any missing fees you find in the document\n"
        "- Remove incorrect entries by listing their indices in removed_indices\n"
        "- Do NOT re-extract fees that are already correct\n"
        "- Focus only on the issues raised\n\n"
        "RULES:\n"
        "- Rebates: negative amounts, is_rebate=true. Fees: positive amounts, is_rebate=false.\n"
        "- All per-contract amounts in USD.\n"
        "- Participant mapping: Public Customer/Priority Customer/Retail → CUSTOMER, "
        "Professional/Professional Customer → PROFESSIONAL, "
        "Market Maker/Specialist/LMM/DPM/PMM/CMM → MARKET_MAKER, "
        "Away Market Maker/Non-Member MM/FarMM → AWAY_MARKET_MAKER, "
        "Firm/Proprietary → FIRM, Broker-Dealer/BD/JBO → BROKER_DEALER\n"
    ),
    retries=1,
)
