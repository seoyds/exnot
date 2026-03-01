"""AI-powered fee schedule extraction using PydanticAI agents.

Thin adapter that preserves the same interface (`AIExtractor.extract()`)
while delegating to the agentic orchestrator pipeline in `exnot.ai.agents`.
"""

import asyncio
import logging
from dataclasses import dataclass, field

from exnot.config import get_settings
from exnot.parser.base import ExtractedDocument

logger = logging.getLogger(__name__)


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
    """Orchestrates AI extraction of fee schedules via PydanticAI agents."""

    def __init__(self):
        settings = get_settings()
        self.confidence_threshold = settings.ai_confidence_threshold
        self.max_retries = settings.ai_max_retries
        self.budget_per_exchange = settings.ai_budget_per_exchange_usd

    def extract(self, document: ExtractedDocument, exchange_code: str) -> ExtractionResult:
        """Run the extraction pipeline. Same interface as before."""
        try:
            loop = asyncio.get_running_loop()
        except RuntimeError:
            loop = None

        if loop and loop.is_running():
            # Already in an async context (e.g., tests) — create a new loop in a thread
            import concurrent.futures

            with concurrent.futures.ThreadPoolExecutor(max_workers=1) as pool:
                return pool.submit(
                    asyncio.run, self._extract_async(document, exchange_code)
                ).result()
        else:
            return asyncio.run(self._extract_async(document, exchange_code))

    async def _extract_async(
        self, document: ExtractedDocument, exchange_code: str
    ) -> ExtractionResult:
        """Async extraction using the orchestrator agent."""
        from exnot.ai.agents.orchestrator import orchestrator_agent
        from exnot.ai.cost import CostTracker
        from exnot.ai.deps import ExtractionDeps
        from exnot.ai.models import ModelRegistry, TaskType
        from exnot.parser.extraction_hints import get_hints_for_exchange
        from exnot.parser.section_splitter import (
            classify_context_sections,
            group_sections,
            split_document,
        )

        settings = get_settings()
        registry = ModelRegistry(settings)
        cost_tracker = CostTracker(
            exchange_code=exchange_code,
            budget_usd=self.budget_per_exchange,
        )

        hints = get_hints_for_exchange(exchange_code)
        exchange_hints = hints.get("prompt_addition", "")

        # Pre-split document into sections and groups BEFORE the orchestrator runs
        format_hint = document.metadata.get("parser", "pdf")
        sections = split_document(document, format_hint=format_hint)
        sections = classify_context_sections(sections)
        fee_sections = [s for s in sections if not s.is_context]
        section_groups = group_sections(fee_sections, char_budget=settings.ai_section_char_budget)

        logger.info(
            f"[{exchange_code}] Pre-split: {len(sections)} sections, "
            f"{len(fee_sections)} fee-bearing, {len(section_groups)} groups "
            f"(budget={settings.ai_section_char_budget} chars/group)"
        )

        deps = ExtractionDeps(
            model_registry=registry,
            cost_tracker=cost_tracker,
            exchange_code=exchange_code,
            exchange_hints=exchange_hints,
            document=document,
            sections=sections,
            section_groups=section_groups,
        )

        # Build orchestrator prompt with pre-computed section plan
        prompt = self._build_orchestrator_prompt(document, exchange_code, sections, section_groups)

        model = registry.get_model(TaskType.ORCHESTRATOR)
        logger.info(f"[{exchange_code}] Starting agentic extraction pipeline")

        from pydantic_ai.settings import ModelSettings

        agent_result = await orchestrator_agent.run(
            prompt,
            deps=deps,
            model=model,
            model_settings=ModelSettings(max_tokens=16384),
        )

        # Track orchestrator cost
        model_name = registry.get_model_name(TaskType.ORCHESTRATOR)
        cost_tracker.record(
            task="orchestrator",
            model=model_name,
            usage=agent_result.usage(),
        )

        typed_output = agent_result.output

        # Convert typed output -> legacy ExtractionResult
        result = ExtractionResult(
            raw_fees=[fee.model_dump() for fee in typed_output.fees],
            confidence=typed_output.validation_confidence or self._compute_confidence_heuristic(typed_output),
            exchange_name=typed_output.exchange_name,
            effective_date=typed_output.effective_date,
            extraction_notes=typed_output.extraction_notes,
            ai_calls_made=len(cost_tracker.calls),
            total_tokens_used=cost_tracker.total_tokens,
            structural_analysis=cost_tracker.summary(),
        )

        logger.info(
            f"[{exchange_code}] Agentic extraction complete. "
            f"{len(result.raw_fees)} fees, confidence={result.confidence:.2f}, "
            f"AI calls={result.ai_calls_made}, tokens={result.total_tokens_used}, "
            f"cost=${cost_tracker.total_cost_usd:.4f}"
        )

        return result

    def _build_orchestrator_prompt(
        self, document: ExtractedDocument, exchange_code: str,
        sections: list | None = None, section_groups: list | None = None,
    ) -> str:
        """Build a compact prompt for the orchestrator with pre-computed section plan."""
        # Orchestrator gets a summary, not the full document (that's what tools are for)
        table_summaries = []
        for i, table in enumerate(document.tables[:20]):
            headers = " | ".join(table.headers[:8]) if table.headers else "(no headers)"
            table_summaries.append(
                f"  Table {i}: {table.title or '(untitled)'} — {len(table.rows)} rows — {headers}"
            )

        tables_text = "\n".join(table_summaries) if table_summaries else "  (no tables)"

        # First 2000 chars of text for headings/structure overview
        text_preview = document.full_text[:2000]

        markdown = document.metadata.get("markdown")
        format_info = "Docling markdown" if markdown else "PDF/HTML text + tables"

        prompt_parts = [
            f"Extract all fee data from this {exchange_code} options exchange fee schedule.\n",
            f"Document format: {format_info}",
            f"Text length: {len(document.full_text)} chars",
            f"Tables: {len(document.tables)}",
            tables_text,
            f"\nText preview (first 2000 chars):\n{text_preview}\n",
        ]

        # Include pre-computed section plan so orchestrator knows exactly what to extract
        if sections and section_groups:
            prompt_parts.append("== PRE-COMPUTED SECTION PLAN ==")
            prompt_parts.append(f"Total sections: {len(sections)}")

            for i, s in enumerate(sections):
                label = "(context)" if s.is_context else "(fee-bearing)"
                prompt_parts.append(
                    f"  Section {i}: {s.heading[:80]} — {s.char_count} chars, "
                    f"{len(s.tables)} tables {label}"
                )

            prompt_parts.append(f"\nExtraction groups ({len(section_groups)}):")
            for gi, group in enumerate(section_groups):
                # Map group section indices back to global section indices
                global_indices = []
                for gs in group.sections:
                    for si, s in enumerate(sections):
                        if s is gs:
                            global_indices.append(si)
                            break
                headings = [s.heading[:40] for s in group.sections]
                prompt_parts.append(
                    f"  Group {gi}: sections {global_indices} — {group.total_chars} chars — {headings}"
                )

            prompt_parts.append(
                "\nYou MUST call extract_section once for EACH group above. "
                "Do NOT combine groups or skip any. "
                "After all groups are extracted, call validate_extraction on the merged result."
            )
        else:
            prompt_parts.append(
                "Use get_document_sections to plan the extraction, then extract_section for each group."
            )

        return "\n".join(prompt_parts)

    def _compute_confidence_heuristic(self, output) -> float:
        """Fallback heuristic confidence if validator didn't run."""
        fees = output.fees
        if not fees:
            return 0.0

        score = 1.0
        participant_types = {f.participant_type for f in fees}
        fee_types = {f.fee_type for f in fees}

        if "CUSTOMER" not in participant_types:
            score -= 0.3
        if "MAKER" not in fee_types:
            score -= 0.2
        if "TAKER" not in fee_types:
            score -= 0.2
        if len(participant_types) < 2:
            score -= 0.15
        if len(fees) < 4:
            score -= 0.2
        elif len(fees) < 10:
            score -= 0.1

        return max(0.0, min(1.0, score))
