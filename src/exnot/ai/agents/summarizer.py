"""Change summary agent — CHEAP tier.

Generates concise natural-language summaries of fee schedule changes.
"""

from __future__ import annotations

from pydantic_ai import Agent, ToolOutput

from exnot.ai.deps import SummaryDeps
from exnot.ai.types import ChangeSummary

summarizer_agent = Agent[SummaryDeps, ChangeSummary](
    "test",
    deps_type=SummaryDeps,
    output_type=ToolOutput(ChangeSummary, name="return_summary"),
    instructions=(
        "You summarize fee schedule changes for US options exchanges.\n"
        "Write 2-3 concise sentences for financial professionals.\n"
        "Focus on the most impactful changes (largest $ changes, "
        "changes affecting Customer/Market Maker fees).\n"
        "Mention if the exchange is becoming more or less competitive.\n"
        "Set impact_level to HIGH if any change > $0.05/contract or affects Customer maker/taker, "
        "MEDIUM if changes are $0.01-$0.05, LOW otherwise.\n"
    ),
    retries=1,
)
