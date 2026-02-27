"""AI-powered fee schedule extraction using Anthropic Claude.

Optimized single-stage pipeline:
  Stage 1: Text/table extraction (handled by pdf_parser/html_parser)
  Stage 2: AI fee data extraction (single call - structural analysis + extraction combined)
  Stage 3: Validation & confidence scoring
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

# Max table rows to send per table (avoids blowing up token count)
MAX_TABLE_ROWS = 50

FEE_EXTRACTION_PROMPT = """You are a financial data extraction specialist for US options exchange fee schedules.

Analyze the document and extract ALL fee and rebate amounts. For EVERY fee entry, provide a JSON object with these EXACT field names and enum values:

{{
  "fee_code": "<exchange billing code or null>",
  "participant_type": "CUSTOMER" | "PROFESSIONAL" | "MARKET_MAKER" | "AWAY_MARKET_MAKER" | "FIRM" | "BROKER_DEALER" | "NON_CUSTOMER" | "ALL",
  "contra_party_type": "<same enum as participant_type, or null if fee doesn't depend on contra>",
  "security_class": "PENNY" | "NON_PENNY" | "INDEX" | "EQUITY" | "ETF" | "MINI" | "SPY" | "QQQ" | "IWM" | "NDX" | "RUT" | "VIX" | "ALL",
  "symbol": "<specific symbol like SPY, NDX, RUT if the fee is symbol-specific, else null>",
  "order_type": "SIMPLE" | "COMPLEX" | "AUCTION" | "PIM" | "CROSSING" | "DIRECTED" | "QCC" | "FLEX" | "OPENING" | "ROUTED" | "ALL",
  "fee_type": "MAKER" | "TAKER" | "ROUTING" | "CROSSING_FEE" | "PIM_FEE" | "RESPONSE_FEE" | "BREAK_UP_REBATE" | "SURCHARGE" | "ORF" | "TRANSACTION" | "CLEARING" | "CONNECTIVITY" | "MARKET_DATA" | "MEMBERSHIP" | "CANCELLATION" | "STOCK_HANDLING",
  "fee_unit": "PER_CONTRACT" | "PER_CONTRACT_SIDE" | "PER_SHARE" | "MONTHLY_FLAT" | "PER_PORT_MONTHLY" | "PERCENTAGE" | "PER_ORDER",
  "amount": <decimal number in USD>,
  "is_rebate": <true if rebate/credit, false if fee>,
  "routing_destination": "<target exchange(s) for routed orders, or null>",
  "tier_group": "<group name for related tiers like 'customer_penny_add', or null if not tiered>",
  "tier_number": <0 for base rate, 1+ for volume tiers, or null if not tiered>,
  "tier_conditions": <structured condition object or null>,
  "conditions": <object with footnotes, caps, exclusions, etc. or null>,
  "section_ref": "<section name/number in source document>",
  "notes": "<any qualifiers or footnotes>"
}}

TIER CONDITIONS FORMAT (when tier_conditions is not null):
{{
  "logic": "AND" | "OR",
  "criteria": [
    {{
      "metric": "ADAV" | "ADRV" | "ADV" | "NBBO_PCT" | "TOTAL_VOLUME" | "CCV_PCT" | "CROSS_ASSET",
      "capacities": ["CUSTOMER", "MARKET_MAKER"],
      "security_filter": "PENNY" | null,
      "operator": ">=" | "<=" | ">" | "<",
      "value": 0.0050,
      "unit": "PCT_OCV" | "PCT_CCV" | "PCT_TCV" | "CONTRACTS" | "PERCENT",
      "description": "Human-readable description of this criterion"
    }}
  ]
}}

RULES:
- Rebates: negative amounts, is_rebate=true. Fees: positive amounts, is_rebate=false.
- All per-contract amounts in USD per contract.
- Participant mapping: "Public Customer"/"Priority Customer"/"Retail" → CUSTOMER; "Professional"/"Professional Customer" → PROFESSIONAL; "Market Maker"/"Specialist"/"LMM"/"DPM"/"PMM"/"CMM" → MARKET_MAKER; "Away Market Maker"/"Non-Member MM"/"FarMM" → AWAY_MARKET_MAKER; "Firm"/"Proprietary" → FIRM; "Broker-Dealer"/"BD"/"JBO" → BROKER_DEALER; grouped non-customer → NON_CUSTOMER
- When a fee depends on the contra-party (e.g., "Customer vs Non-Customer"), set contra_party_type.
- Include ALL volume tiers — each tier is a separate fee entry with the same fee_code but different tier_number and tier_conditions.
- Base/default rates have tier_number=0 and tier_conditions=null.
- For tiered entries, tier_group links related tiers (e.g., all "Customer Penny Add" tiers share tier_group="customer_penny_add").
- Extract EVERY fee mentioned including ORF, routing, surcharges, etc.
- Focus on OPTIONS transaction fees. Skip market data, connectivity, and membership fees unless they are per-contract.

{exchange_hints}

Return JSON:
{{
  "exchange_name": "<name>",
  "effective_date": "<date or null>",
  "fees": [<array of fee objects>],
  "extraction_notes": "<notes about extraction>"
}}"""

SELF_QUESTION_PROMPT = """You previously extracted fee data from a US options exchange fee schedule, but the extraction may be incomplete.

Previous extraction ({fee_count} fees):
{previous_extraction}

Issues identified:
{issues}

Re-examine the document and provide corrected/additional fee entries focusing on the issues above.

Return JSON:
{{
  "corrections": [<fee objects to add or replace>],
  "removed_indices": [<indices of incorrect fees>],
  "confidence": <0.0 to 1.0>,
  "notes": "<explanation>"
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
    """Orchestrates AI extraction of fee schedules."""

    def __init__(self):
        settings = get_settings()
        self.client = anthropic.Anthropic(api_key=settings.anthropic_api_key)
        self.model = settings.ai_model
        self.max_tokens = settings.ai_max_tokens
        self.confidence_threshold = settings.ai_confidence_threshold
        self.max_retries = settings.ai_max_retries

    def _call_api(self, messages: list[dict], max_tokens: int | None = None) -> tuple[str, str, int, int]:
        """Call Claude API using streaming.

        Returns (response_text, stop_reason, input_tokens, output_tokens) tuple.
        """
        tokens = max_tokens or self.max_tokens
        text_parts = []
        stop_reason = ""
        input_tokens = 0
        output_tokens = 0

        try:
            with self.client.messages.stream(
                model=self.model,
                max_tokens=tokens,
                messages=messages,
            ) as stream:
                for text in stream.text_stream:
                    text_parts.append(text)
                final = stream.get_final_message()
                stop_reason = final.stop_reason
                input_tokens = final.usage.input_tokens
                output_tokens = final.usage.output_tokens
        except anthropic.RateLimitError:
            raise  # Let caller handle retries

        return "".join(text_parts), stop_reason, input_tokens, output_tokens

    def _build_document_context(self, document: ExtractedDocument) -> str:
        """Build a compact document context string for AI calls."""
        # Truncate full text (large PDFs like BOX can be 50K+ chars)
        full_text = document.full_text[:60000]

        # Build table text with row limits
        tables_text = ""
        for i, table in enumerate(document.tables):
            tables_text += f"\n--- Table {i + 1}: {table.title} ---\n"
            tables_text += f"Headers: {table.headers}\n"
            rows_to_send = table.rows[:MAX_TABLE_ROWS]
            for row in rows_to_send:
                tables_text += f"  {row}\n"
            if len(table.rows) > MAX_TABLE_ROWS:
                tables_text += f"  ... ({len(table.rows)} total rows, showing first {MAX_TABLE_ROWS})\n"
            if table.footnotes:
                tables_text += f"Footnotes: {table.footnotes}\n"

        return f"DOCUMENT TEXT:\n{full_text}\n\nEXTRACTED TABLES:\n{tables_text}"

    def extract(self, document: ExtractedDocument, exchange_code: str) -> ExtractionResult:
        """Run the extraction pipeline."""
        from exnot.parser.extraction_hints import get_hints_for_exchange

        result = ExtractionResult()

        # Single-stage extraction (structural analysis + fee extraction combined)
        logger.info(f"[{exchange_code}] Extracting fee data...")
        context = self._build_document_context(document)

        # Inject exchange-family-specific hints into the prompt
        hints = get_hints_for_exchange(exchange_code)
        exchange_hints = hints.get("prompt_addition", "")
        prompt = FEE_EXTRACTION_PROMPT.replace("{exchange_hints}", exchange_hints)

        text, stop_reason, in_tok, out_tok = self._call_api(
            [{"role": "user", "content": f"{prompt}\n\n{context}"}],
        )
        result.ai_calls_made += 1
        result.total_tokens_used += in_tok + out_tok
        logger.info(f"[{exchange_code}] AI call 1: {in_tok} in, {out_tok} out tokens")

        if stop_reason == "max_tokens":
            logger.warning(f"[{exchange_code}] Response truncated by max_tokens, attempting salvage")

        extraction = self._parse_json_response(text)
        result.raw_fees = extraction.get("fees", [])
        result.exchange_name = extraction.get("exchange_name", exchange_code)
        result.effective_date = extraction.get("effective_date")
        result.extraction_notes = extraction.get("extraction_notes", "")

        # Validation & confidence scoring
        logger.info(f"[{exchange_code}] Validating extraction...")
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

            corrections_text, _, in_tok, out_tok = self._call_api(
                [{"role": "user", "content": self._build_self_question_prompt(document, result, issues)}],
            )
            result.ai_calls_made += 1
            result.total_tokens_used += in_tok + out_tok
            logger.info(f"[{exchange_code}] AI call {result.ai_calls_made}: {in_tok} in, {out_tok} out tokens")

            corrections = self._parse_json_response(corrections_text)
            result = self._apply_corrections(result, corrections)
            result.confidence = self._compute_confidence(result, document)

        logger.info(
            f"[{exchange_code}] Extraction complete. "
            f"{len(result.raw_fees)} fees, confidence={result.confidence:.2f}, "
            f"AI calls={result.ai_calls_made}, tokens={result.total_tokens_used}"
        )
        return result

    def _build_self_question_prompt(
        self, document: ExtractedDocument, result: ExtractionResult, issues: str
    ) -> str:
        """Build the self-question prompt with document context."""
        prompt = SELF_QUESTION_PROMPT.format(
            fee_count=len(result.raw_fees),
            previous_extraction=json.dumps(result.raw_fees[:20], indent=2),
            issues=issues,
        )
        context = self._build_document_context(document)
        return f"{prompt}\n\n{context}"

    def _compute_confidence(self, result: ExtractionResult, document: ExtractedDocument) -> float:
        """Compute confidence score for the extraction."""
        score = 1.0
        fees = result.raw_fees

        if not fees:
            return 0.0

        has_customer = any(f.get("participant_type") == "CUSTOMER" for f in fees)
        has_maker = any(f.get("fee_type") == "MAKER" for f in fees)
        has_taker = any(f.get("fee_type") == "TAKER" for f in fees)

        if not has_customer:
            score -= 0.3
        if not has_maker:
            score -= 0.2
        if not has_taker:
            score -= 0.2

        for fee in fees:
            amount = abs(fee.get("amount", 0))
            if amount > 3.0:
                score -= 0.05

        participant_types = {f.get("participant_type") for f in fees}
        if len(participant_types) < 2:
            score -= 0.15

        security_classes = {f.get("security_class") for f in fees}
        if "PENNY" not in security_classes and "NON_PENNY" not in security_classes:
            score -= 0.1

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

    def _apply_corrections(self, result: ExtractionResult, corrections: dict) -> ExtractionResult:
        """Apply corrections from self-questioning."""
        removed_indices = set(corrections.get("removed_indices", []))
        if removed_indices:
            result.raw_fees = [
                f for i, f in enumerate(result.raw_fees) if i not in removed_indices
            ]

        new_fees = corrections.get("corrections", [])
        result.raw_fees.extend(new_fees)

        return result

    def _parse_json_response(self, text: str) -> dict:
        """Parse JSON from Claude's response, handling markdown code blocks and truncation."""
        text = text.strip()

        # Extract content from markdown code fences (handles preamble text before ```)
        import re
        fence_match = re.search(r"```(?:json)?\s*\n(.*?)(?:```|$)", text, re.DOTALL)
        if fence_match:
            text = fence_match.group(1).strip()
        elif text.startswith("```"):
            lines = text.split("\n")
            lines = [line for line in lines if not line.strip().startswith("```")]
            text = "\n".join(lines)

        try:
            return json.loads(text)
        except json.JSONDecodeError as e:
            logger.warning(f"Initial JSON parse failed: {e}")
            start = text.find("{")
            end = text.rfind("}") + 1
            if start >= 0 and end > start:
                try:
                    return json.loads(text[start:end])
                except json.JSONDecodeError:
                    pass

            if start >= 0:
                result = self._salvage_truncated_json(text[start:])
                if result:
                    return result

            logger.error(f"Failed to parse JSON from AI response (len={len(text)}): {text[:300]}...")
            return {}

    def _salvage_truncated_json(self, text: str) -> dict | None:
        """Attempt to recover partial data from truncated JSON responses."""
        last_complete = text.rfind("},")
        if last_complete < 0:
            return None

        partial = text[:last_complete + 1]

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
