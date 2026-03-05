"""Protocol specification extraction agent — extracts billing codes from FIX/binary specs."""

from __future__ import annotations

from pydantic_ai import Agent, ToolOutput

from exnot.ai.deps import DiscoveryDeps
from exnot.ai.types import ProtocolExtractionResult

protocol_extractor_agent = Agent[DiscoveryDeps, ProtocolExtractionResult](
    # Model is overridden at call site via model= parameter
    "test",
    deps_type=DiscoveryDeps,
    output_type=ToolOutput(ProtocolExtractionResult, name="return_billing_codes"),
    instructions=(
        "You are a billing code extractor for US options exchange protocol specifications. "
        "Given text from a FIX protocol or binary order entry specification document, "
        "extract all billing codes, transaction type codes, and fee-related identifiers.\n\n"
        "For each code, provide:\n"
        "- code: The billing/transaction code string\n"
        "- protocol: FIX, BINARY, SRO, or OTHER\n"
        "- description: What this code represents\n"
        "- tag_number: The FIX tag number if applicable (e.g., tag 20116)\n"
        "- fee_type_hint: The most likely FeeType this maps to "
        "(MAKER, TAKER, ROUTING, ORF, TRANSACTION, CLEARING, etc.)\n\n"
        "Focus on codes related to transaction fees, rebates, and billing. "
        "Ignore purely routing or session-level protocol codes."
    ),
    retries=1,
)
