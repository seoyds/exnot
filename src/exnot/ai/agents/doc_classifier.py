"""Document classification agent — categorizes discovered URLs into document types."""

from pydantic_ai import Agent, ToolOutput

from exnot.ai.deps import DiscoveryDeps
from exnot.ai.types import DocumentClassificationResult

doc_classifier_agent = Agent[DiscoveryDeps, DocumentClassificationResult](
    "test",
    deps_type=DiscoveryDeps,
    output_type=ToolOutput(DocumentClassificationResult, name="return_classification"),
    instructions=(
        "You are a document classifier for US options exchanges. "
        "Given a URL, title, and content preview, classify the document into one of these categories:\n"
        "- FEE_SCHEDULE: Fee schedule, pricing schedule, or fee table document\n"
        "- PROTOCOL_SPEC: FIX protocol specification, binary order entry spec, or technical interface document\n"
        "- REGULATORY_FILING: SEC filing, rule change, regulatory submission\n"
        "- MEMBERSHIP_AGREEMENT: Membership application, trading permit, connectivity agreement\n"
        "- CIRCULAR_NOTICE: Exchange circular, regulatory circular, fee change notice, information memo\n"
        "- OTHER: Does not fit any category above\n\n"
        "Return your classification with a confidence score (0.0-1.0) and brief reasoning."
    ),
    retries=1,
)
