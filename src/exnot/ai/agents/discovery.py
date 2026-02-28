"""URL evaluation agent — CHEAP tier.

Evaluates candidate URLs to find the official fee schedule for a US options exchange.
"""

from __future__ import annotations

from pydantic_ai import Agent, ToolOutput

from exnot.ai.deps import DiscoveryDeps
from exnot.ai.types import UrlEvaluationResult

discovery_agent = Agent[DiscoveryDeps, UrlEvaluationResult](
    # Model is overridden at call site via model= parameter
    "test",
    deps_type=DiscoveryDeps,
    output_type=ToolOutput(UrlEvaluationResult, name="return_evaluation"),
    instructions=(
        "You evaluate search results to find the official fee schedule for a US options exchange.\n\n"
        "RULES:\n"
        "- The fee schedule must be specifically for OPTIONS (not equities, listings, or market data).\n"
        "- Prefer official exchange/operator websites (e.g., cboe.com, nasdaq.com, nyse.com, miaxglobal.com).\n"
        "- Prefer direct links to the fee schedule document (PDF or CSV) over landing pages.\n"
        "- If a landing page links to a downloadable fee schedule, select the landing page as primary.\n"
        "- REJECT: regulatory filings (SEC), news articles, third-party sites, listing guides, market data fees.\n"
        "- If multiple valid URLs exist, pick the best as primary and list others as alternates.\n"
    ),
    retries=1,
)
