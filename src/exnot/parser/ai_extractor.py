"""AI-powered fee schedule extraction using Anthropic Claude.

Implements a multi-stage agentic pipeline:
  Stage 1: Text/table extraction (handled by pdf_parser/html_parser)
  Stage 2: AI structural analysis - understand the document layout
  Stage 3: AI fee data extraction - extract structured fee data
  Stage 4: Validation & confidence scoring
  Agentic loop: self-questioning if confidence < threshold
"""

import json
import logging
import time
from dataclasses import dataclass, field

import anthropic

from exnot.config import get_settings
from exnot.parser.base import ExtractedDocument

logger = logging.getLogger(__name__)

STRUCTURAL_ANALYSIS_PROMPT = """You are a financial document analyst specializing in US options exchange fee schedules.

Analyze the provided fee schedule document and identify ALL of the following:

1. **Fee Tables**: List every fee/pricing table in the document with a brief description.
2. **Participant Categories**: What participant types are used? (e.g., Customer, Professional, Market Maker, Firm, Broker-Dealer, etc.)
3. **Security Classifications**: What security types are distinguished? (e.g., Penny Pilot, Non-Penny, Index Options, ETF, etc.)
4. **Order Types**: What order type distinctions exist? (e.g., Simple, Complex/Multi-leg, Auction, Directed, QCC, etc.)
5. **Fee Types**: What types of fees are listed? (e.g., Maker/Taker, Routing, ORF, Transaction, etc.)
6. **Volume Tiers**: Are there volume-based tiers? If so, describe the tier structure.
7. **Effective Dates**: Any effective dates mentioned.
8. **Important Footnotes**: Key footnotes that modify fee amounts or applicability.

Return your analysis as JSON with this structure:
{
  "tables": [{"name": "...", "description": "...", "location": "page X or section Y"}],
  "participant_types": ["..."],
  "security_classes": ["..."],
  "order_types": ["..."],
  "fee_types": ["..."],
  "volume_tiers": {"has_tiers": true/false, "description": "..."},
  "effective_dates": ["..."],
  "footnotes": ["..."],
  "overall_notes": "Any important high-level observations"
}"""

FEE_EXTRACTION_PROMPT = """You are a financial data extraction specialist. Extract ALL fee and rebate amounts from this US options exchange fee schedule.

For EVERY fee entry in the document, provide a JSON object with these fields:

{{
  "participant_type": "CUSTOMER" | "PROFESSIONAL" | "MARKET_MAKER" | "AWAY_MARKET_MAKER" | "FIRM" | "BROKER_DEALER",
  "security_class": "PENNY" | "NON_PENNY" | "INDEX" | "ETF" | "EQUITY" | "MINI",
  "order_type": "SIMPLE" | "COMPLEX" | "AUCTION" | "DIRECTED" | "QCC",
  "fee_type": "MAKER" | "TAKER" | "ROUTING" | "ORF" | "TRANSACTION" | "CLEARING" | "CONNECTIVITY" | "MARKET_DATA" | "MEMBERSHIP",
  "amount": <decimal number in USD per contract>,
  "is_rebate": <true if this is a rebate/credit, false if a fee>,
  "volume_tier": <string tier name or null if no tier>,
  "tier_threshold": <string description of tier threshold or null>,
  "notes": "<any qualifiers, conditions, or footnotes>"
}}

IMPORTANT RULES:
- Rebates are amounts PAID TO the participant. Use negative values for rebates and set is_rebate=true.
- Fees are amounts CHARGED to the participant. Use positive values for fees and set is_rebate=false.
- All amounts must be in USD per contract (not per share).
- Map exchange-specific participant names to the standardized types above:
  * "Public Customer", "Priority Customer", "Retail" → CUSTOMER
  * "Professional", "Professional Customer" → PROFESSIONAL
  * "Market Maker", "Specialist", "Lead Market Maker", "DPM", "PMM", "LMM" → MARKET_MAKER
  * "Away Market Maker", "Non-Member Market Maker", "Remote Market Maker" → AWAY_MARKET_MAKER
  * "Firm", "Proprietary", "Non-Customer" → FIRM
  * "Broker-Dealer", "BD" → BROKER_DEALER
- If a fee applies to equity options generally (not specifically penny or non-penny), use EQUITY.
- Include ALL tiers if volume-based tiers exist.
- Be thorough - extract EVERY fee mentioned, not just the main transaction fees.

Return a JSON object:
{{
  "exchange_name": "<name of the exchange>",
  "effective_date": "<date if found, or null>",
  "fees": [<array of fee objects>],
  "extraction_notes": "<any notes about the extraction process, uncertainties, or missing data>"
}}"""

SELF_QUESTION_PROMPT = """You previously extracted fee data from a US options exchange fee schedule, but the extraction may be incomplete or uncertain.

Previous extraction result:
{previous_extraction}

Issues identified:
{issues}

Please re-examine the relevant sections of the fee schedule document and provide corrected/additional fee entries. Focus specifically on the issues listed above.

Return your corrections in the same JSON format:
{{
  "corrections": [<fee objects to add or replace>],
  "removed_indices": [<indices of previously extracted fees that were incorrect>],
  "confidence": <0.0 to 1.0>,
  "notes": "<explanation of corrections>"
}}"""


@dataclass
class ExtractionResult:
    """Result of the AI extraction pipeline."""

    structural_analysis: dict = field(default_factory=dict)
    raw_fees: list[dict] = field(default_factory=list)
    confidence: float = 0.0
    exchange_name: str = ""
    effective_date: str | None = None
    extraction_notes: str = ""
    ai_calls_made: int = 0
    total_tokens_used: int = 0


class AIExtractor:
    """Orchestrates multi-stage AI extraction of fee schedules."""

    def __init__(self):
        settings = get_settings()
        self.client = anthropic.Anthropic(api_key=settings.anthropic_api_key)
        self.model = settings.ai_model
        self.max_tokens = settings.ai_max_tokens
        self.confidence_threshold = settings.ai_confidence_threshold
        self.max_retries = settings.ai_max_retries

    def _call_api(self, messages: list[dict]) -> tuple[str, str]:
        """Call Claude API using streaming to avoid timeout on large responses.

        Returns (response_text, stop_reason) tuple.
        """
        text_parts = []
        stop_reason = ""
        with self.client.messages.stream(
            model=self.model,
            max_tokens=self.max_tokens,
            messages=messages,
        ) as stream:
            for text in stream.text_stream:
                text_parts.append(text)
            stop_reason = stream.get_final_message().stop_reason
        return "".join(text_parts), stop_reason

    def extract(self, document: ExtractedDocument, exchange_code: str) -> ExtractionResult:
        """Run the full multi-stage extraction pipeline."""
        result = ExtractionResult()

        # Stage 2: Structural analysis
        logger.info(f"[{exchange_code}] Stage 2: Running structural analysis...")
        result.structural_analysis = self._structural_analysis(document)
        result.ai_calls_made += 1

        # Brief pause between AI calls to stay within rate limits
        logger.info(f"[{exchange_code}] Waiting 65s for rate limit window reset...")
        time.sleep(65)

        # Stage 3: Fee data extraction
        logger.info(f"[{exchange_code}] Stage 3: Extracting fee data...")
        extraction = self._extract_fees(document, result.structural_analysis)
        result.ai_calls_made += 1

        result.raw_fees = extraction.get("fees", [])
        result.exchange_name = extraction.get("exchange_name", exchange_code)
        result.effective_date = extraction.get("effective_date")
        result.extraction_notes = extraction.get("extraction_notes", "")

        # Stage 4: Validation & confidence scoring
        logger.info(f"[{exchange_code}] Stage 4: Validating extraction...")
        result.confidence = self._compute_confidence(result, document)

        # Agentic loop: self-questioning if confidence is low
        attempts = 0
        while result.confidence < self.confidence_threshold and attempts < self.max_retries:
            attempts += 1
            logger.info(
                f"[{exchange_code}] Confidence {result.confidence:.2f} < {self.confidence_threshold}. "
                f"Self-questioning attempt {attempts}/{self.max_retries}..."
            )
            issues = self._identify_issues(result, document)
            if not issues:
                break

            logger.info(f"[{exchange_code}] Waiting 65s for rate limit window reset...")
            time.sleep(65)
            corrections = self._self_question(document, result, issues)
            result.ai_calls_made += 1
            result = self._apply_corrections(result, corrections)
            result.confidence = self._compute_confidence(result, document)

        logger.info(
            f"[{exchange_code}] Extraction complete. "
            f"{len(result.raw_fees)} fees, confidence={result.confidence:.2f}, "
            f"AI calls={result.ai_calls_made}"
        )
        return result

    def _structural_analysis(self, document: ExtractedDocument) -> dict:
        """Stage 2: Analyze document structure."""
        # Build context from extracted tables
        tables_text = ""
        for i, table in enumerate(document.tables):
            tables_text += f"\n--- Table {i+1}: {table.title} ---\n"
            tables_text += f"Headers: {table.headers}\n"
            for row in table.rows[:5]:  # First 5 rows as sample
                tables_text += f"  {row}\n"
            if len(table.rows) > 5:
                tables_text += f"  ... ({len(table.rows)} total rows)\n"

        # Truncate full text to fit context (keep small for rate-limited APIs)
        full_text = document.full_text[:8000]

        content = f"DOCUMENT TEXT:\n{full_text}\n\nEXTRACTED TABLES:\n{tables_text}"

        text, _ = self._call_api([
            {"role": "user", "content": f"{STRUCTURAL_ANALYSIS_PROMPT}\n\n{content}"}
        ])

        return self._parse_json_response(text)

    def _extract_fees(self, document: ExtractedDocument, structure: dict) -> dict:
        """Stage 3: Extract structured fee data."""
        # Build comprehensive context
        tables_text = ""
        for i, table in enumerate(document.tables):
            tables_text += f"\n--- Table {i+1}: {table.title} ---\n"
            tables_text += f"Headers: {table.headers}\n"
            for row in table.rows:
                tables_text += f"  {row}\n"
            if table.footnotes:
                tables_text += f"Footnotes: {table.footnotes}\n"

        full_text = document.full_text[:10000]

        context = (
            f"STRUCTURAL ANALYSIS:\n{json.dumps(structure, indent=2)}\n\n"
            f"DOCUMENT TEXT:\n{full_text}\n\n"
            f"EXTRACTED TABLES:\n{tables_text}"
        )

        text, stop_reason = self._call_api([
            {"role": "user", "content": f"{FEE_EXTRACTION_PROMPT}\n\n{context}"}
        ])

        if stop_reason == "max_tokens":
            logger.warning("Fee extraction response was truncated by max_tokens limit")

        return self._parse_json_response(text)

    def _compute_confidence(self, result: ExtractionResult, document: ExtractedDocument) -> float:
        """Stage 4: Compute confidence score for the extraction."""
        score = 1.0
        fees = result.raw_fees

        if not fees:
            return 0.0

        # Check: minimum expected fees (at least customer maker/taker for penny)
        has_customer = any(f.get("participant_type") == "CUSTOMER" for f in fees)
        has_maker = any(f.get("fee_type") == "MAKER" for f in fees)
        has_taker = any(f.get("fee_type") == "TAKER" for f in fees)

        if not has_customer:
            score -= 0.3
        if not has_maker:
            score -= 0.2
        if not has_taker:
            score -= 0.2

        # Check: amounts in reasonable range (most option fees are $0.00 - $2.00)
        for fee in fees:
            amount = abs(fee.get("amount", 0))
            if amount > 3.0:
                score -= 0.05  # Unusual but possible for index options

        # Check: at least 2 participant types
        participant_types = {f.get("participant_type") for f in fees}
        if len(participant_types) < 2:
            score -= 0.15

        # Check: has both penny and non-penny (most exchanges do)
        security_classes = {f.get("security_class") for f in fees}
        if "PENNY" not in security_classes and "NON_PENNY" not in security_classes:
            score -= 0.1

        # Check: reasonable number of fees (at least 4 for a minimal schedule)
        if len(fees) < 4:
            score -= 0.2
        elif len(fees) < 10:
            score -= 0.1

        return max(0.0, min(1.0, score))

    def _identify_issues(self, result: ExtractionResult, document: ExtractedDocument) -> str:
        """Identify what's missing or uncertain in the extraction."""
        issues = []
        fees = result.raw_fees

        participant_types = {f.get("participant_type") for f in fees}
        if "CUSTOMER" not in participant_types:
            issues.append("Missing Customer/Retail fees")
        if "MARKET_MAKER" not in participant_types:
            issues.append("Missing Market Maker fees")

        fee_types = {f.get("fee_type") for f in fees}
        if "MAKER" not in fee_types:
            issues.append("Missing Maker fees/rebates")
        if "TAKER" not in fee_types:
            issues.append("Missing Taker fees")

        security_classes = {f.get("security_class") for f in fees}
        if "PENNY" not in security_classes and "NON_PENNY" not in security_classes:
            issues.append("Missing Penny Pilot / Non-Penny classification")

        if len(fees) < 10:
            issues.append(
                f"Only {len(fees)} fees extracted - typical exchange schedules have 20-100+ fee entries"
            )

        return "; ".join(issues) if issues else ""

    def _self_question(
        self, document: ExtractedDocument, result: ExtractionResult, issues: str
    ) -> dict:
        """Agentic self-questioning loop."""
        prompt = SELF_QUESTION_PROMPT.format(
            previous_extraction=json.dumps(result.raw_fees[:20], indent=2),  # First 20
            issues=issues,
        )

        full_text = document.full_text[:10000]
        content = f"{prompt}\n\nDOCUMENT TEXT:\n{full_text}"

        text, _ = self._call_api([{"role": "user", "content": content}])

        return self._parse_json_response(text)

    def _apply_corrections(self, result: ExtractionResult, corrections: dict) -> ExtractionResult:
        """Apply corrections from self-questioning to the extraction result."""
        # Remove incorrect entries
        removed_indices = set(corrections.get("removed_indices", []))
        if removed_indices:
            result.raw_fees = [
                f for i, f in enumerate(result.raw_fees) if i not in removed_indices
            ]

        # Add new/corrected entries
        new_fees = corrections.get("corrections", [])
        result.raw_fees.extend(new_fees)

        return result

    def _parse_json_response(self, text: str) -> dict:
        """Parse JSON from Claude's response, handling markdown code blocks and truncation."""
        # Strip markdown code fences if present
        text = text.strip()
        if text.startswith("```"):
            lines = text.split("\n")
            lines = [line for line in lines if not line.strip().startswith("```")]
            text = "\n".join(lines)

        try:
            return json.loads(text)
        except json.JSONDecodeError as e:
            logger.warning(f"Initial JSON parse failed: {e}")
            # Try to find JSON within the text
            start = text.find("{")
            end = text.rfind("}") + 1
            if start >= 0 and end > start:
                try:
                    return json.loads(text[start:end])
                except json.JSONDecodeError:
                    pass

            # Handle truncated JSON by finding the last complete fee object in the array
            if start >= 0:
                result = self._salvage_truncated_json(text[start:])
                if result:
                    return result

            logger.error(f"Failed to parse JSON from AI response (len={len(text)}): {text[:300]}...")
            return {}

    def _salvage_truncated_json(self, text: str) -> dict | None:
        """Attempt to recover partial data from truncated JSON responses."""
        # Find the last complete object boundary ("},") in the fees array
        # then close the array and outer object
        last_complete = text.rfind("},")
        if last_complete < 0:
            return None

        # Take up to and including the last complete object
        partial = text[:last_complete + 1]

        # Try closing with various suffixes to match the structure
        for suffix in ['\n  ],\n  "extraction_notes": "Truncated response"\n}',
                       ']}', ']\n}']:
            try:
                result = json.loads(partial + suffix)
                fee_count = len(result.get("fees", result.get("corrections", [])))
                logger.warning(f"Salvaged truncated JSON with {fee_count} entries")
                return result
            except json.JSONDecodeError:
                continue

        return None
