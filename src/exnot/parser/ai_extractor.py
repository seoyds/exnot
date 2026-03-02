"""AI-powered fee schedule extraction using PydanticAI agents.

Thin adapter that preserves the same interface (`AIExtractor.extract()`)
while delegating to the agentic orchestrator pipeline in `exnot.ai.agents`.
"""

import asyncio
import logging
import time
from dataclasses import dataclass, field

from exnot.config import get_settings
from exnot.db.models import AgentEventType
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

    def extract(
        self,
        document: ExtractedDocument,
        exchange_code: str,
        event_emitter=None,
    ) -> ExtractionResult:
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
                    asyncio.run,
                    self._extract_async(document, exchange_code, event_emitter=event_emitter),
                ).result()
        else:
            return asyncio.run(self._extract_async(document, exchange_code, event_emitter=event_emitter))

    async def _extract_async(
        self,
        document: ExtractedDocument,
        exchange_code: str,
        event_emitter=None,
    ) -> ExtractionResult:
        """Async extraction: direct group iteration + validation/correction agents."""
        from pydantic_ai.settings import ModelSettings

        from exnot.ai.agents.section_extractor import section_extractor_agent
        from exnot.ai.cost import CostTracker
        from exnot.ai.deps import ExtractionDeps
        from exnot.ai.models import ModelRegistry, TaskType
        from exnot.parser.extraction_hints import get_hints_for_exchange
        from exnot.parser.section_splitter import (
            classify_context_sections,
            group_sections,
            split_document,
        )
        from exnot.parser.table_classifier import classify_tables as rule_classify_tables

        settings = get_settings()
        registry = ModelRegistry(settings)
        cost_tracker = CostTracker(
            exchange_code=exchange_code,
            budget_usd=self.budget_per_exchange,
        )

        hints = get_hints_for_exchange(exchange_code)
        exchange_hints = hints.get("prompt_addition", "")

        # Pre-split document into sections and groups
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
            event_emitter=event_emitter,
        )

        logger.info(f"[{exchange_code}] Starting direct extraction pipeline")

        # Build context text from definitions/footnotes sections
        context_sections = [s for s in sections if s.is_context]
        context_text = self._build_context_text(context_sections)

        # Extract from each group directly (no orchestrator needed)
        MAX_TABLE_ROWS = 50
        extraction_model = registry.get_model(TaskType.FEE_EXTRACTION)
        extraction_model_name = registry.get_model_name(TaskType.FEE_EXTRACTION)

        for gi, group in enumerate(section_groups):
            if cost_tracker.is_over_budget:
                logger.warning(f"[{exchange_code}] Over budget at group {gi}, stopping extraction")
                break

            headings = [s.heading[:40] for s in group.sections]
            section_info = f"Group {gi}: {', '.join(headings)}"

            # Build section content
            section_text_parts: list[str] = []
            section_tables_parts: list[str] = []

            for section in group.sections:
                section_text_parts.append(f"--- {section.heading} ---")
                section_text_parts.append(section.text)

                if section.tables:
                    classifications = rule_classify_tables(section.tables)
                    for j, table in enumerate(section.tables):
                        is_fee = classifications[j].is_fee_table if j < len(classifications) else True
                        if not is_fee:
                            continue
                        section_tables_parts.append(f"\n--- Table: {table.title} ---")
                        section_tables_parts.append(f"Headers: {table.headers}")
                        for row in table.rows[:MAX_TABLE_ROWS]:
                            section_tables_parts.append(f"  {row}")
                        if len(table.rows) > MAX_TABLE_ROWS:
                            section_tables_parts.append(f"  ... ({len(table.rows)} rows total)")
                        if table.footnotes:
                            section_tables_parts.append(f"Footnotes: {table.footnotes}")

            prompt_parts = [f"Extract fees from: {section_info}"]
            prompt_parts.append(f"\nSECTION DATA:\n{''.join(section_text_parts)}")
            if section_tables_parts:
                prompt_parts.append(f"\nSECTION TABLES:\n{''.join(section_tables_parts)}")
            if context_text:
                prompt_parts.append(f"\nREFERENCE CONTEXT (definitions, footnotes, glossary):\n{context_text}")
            if exchange_hints:
                prompt_parts.append(f"\n{exchange_hints}")

            prompt = "\n".join(prompt_parts)

            # Emit AI_CALL_START event
            if event_emitter:
                try:
                    event_emitter.emit(
                        AgentEventType.AI_CALL_START,
                        f"extract_section:{section_info[:50]}",
                        model=extraction_model_name,
                        prompt_text=prompt,
                    )
                except Exception:
                    pass

            start_time = time.time()
            result = await section_extractor_agent.run(
                prompt,
                deps=deps,
                model=extraction_model,
                model_settings=ModelSettings(max_tokens=16384),
            )
            elapsed_ms = int((time.time() - start_time) * 1000)

            cost = cost_tracker.record(
                task=f"extract_section:{section_info[:50]}",
                model=extraction_model_name,
                usage=result.usage(),
            )

            output = result.output
            fee_dicts = [f.model_dump() for f in output.fees]
            deps.extracted_fees.extend(fee_dicts)

            # Emit AI_CALL_COMPLETE event
            if event_emitter:
                try:
                    event_emitter.emit(
                        AgentEventType.AI_CALL_COMPLETE,
                        f"extract_section:{section_info[:50]}",
                        model=extraction_model_name,
                        response_text=str([f.model_dump() for f in output.fees][:5]),
                        input_tokens=result.usage().input_tokens or 0,
                        output_tokens=result.usage().output_tokens or 0,
                        cost_usd=cost,
                        latency_ms=elapsed_ms,
                    )
                except Exception:
                    pass

            logger.info(
                f"[{exchange_code}] Group {gi}/{len(section_groups) - 1}: "
                f"{len(output.fees)} fees (total {len(deps.extracted_fees)})"
            )

        # Run validation if we have fees and budget remaining
        raw_fees = deps.extracted_fees
        confidence = self._compute_confidence_from_fees(raw_fees)

        if raw_fees and not cost_tracker.is_over_budget:
            confidence = await self._run_validation(deps, cost_tracker, registry)

        # Build result
        result = ExtractionResult(
            raw_fees=raw_fees,
            confidence=confidence,
            exchange_name=exchange_code,
            extraction_notes=f"Extracted from {len(section_groups)} groups",
            ai_calls_made=len(cost_tracker.calls),
            total_tokens_used=cost_tracker.total_tokens,
            structural_analysis=cost_tracker.summary(),
        )

        logger.info(
            f"[{exchange_code}] Extraction complete. "
            f"{len(result.raw_fees)} fees, confidence={result.confidence:.2f}, "
            f"AI calls={result.ai_calls_made}, tokens={result.total_tokens_used}, "
            f"cost=${cost_tracker.total_cost_usd:.4f}"
        )

        return result

    def _build_context_text(self, context_sections: list) -> str:
        """Build reference context from definitions/footnotes sections."""
        parts: list[str] = []
        for s in context_sections:
            parts.append(f"--- {s.heading} ---")
            parts.append(s.text[:3000])
            for table in s.tables[:3]:
                parts.append(f"Table: {table.title}")
                parts.append(f"Headers: {table.headers}")
                for row in table.rows[:20]:
                    parts.append(f"  {row}")
        return "\n".join(parts)[:8000]

    async def _run_validation(
        self,
        deps,
        cost_tracker,
        registry,
    ) -> float:
        """Run fee validation agent and return confidence score."""
        import json

        from pydantic_ai.settings import ModelSettings

        from exnot.ai.agents.fee_validator import fee_validator_agent
        from exnot.ai.models import TaskType

        fees_json = json.dumps(deps.extracted_fees)
        prompt = (
            f"Validate these extracted fees for {deps.exchange_code}.\n\n"
            f"Extracted fees ({len(deps.extracted_fees)} entries):\n{fees_json}\n"
        )

        model = deps.model_registry.get_model(TaskType.FEE_VALIDATION)
        model_name = deps.model_registry.get_model_name(TaskType.FEE_VALIDATION)
        event_emitter = deps.event_emitter

        # Emit AI_CALL_START for validation
        if event_emitter:
            try:
                event_emitter.emit(
                    AgentEventType.AI_CALL_START,
                    "validate_extraction",
                    model=model_name,
                    prompt_text=prompt,
                )
            except Exception:
                pass

        try:
            start_time = time.time()
            result = await fee_validator_agent.run(
                prompt,
                deps=deps,
                model=model,
                model_settings=ModelSettings(max_tokens=8192),
            )
            elapsed_ms = int((time.time() - start_time) * 1000)

            cost = cost_tracker.record(
                task="validate_extraction",
                model=model_name,
                usage=result.usage(),
            )

            # Emit AI_CALL_COMPLETE for validation
            if event_emitter:
                try:
                    event_emitter.emit(
                        AgentEventType.AI_CALL_COMPLETE,
                        "validate_extraction",
                        model=model_name,
                        response_text=str(result.output.model_dump()),
                        input_tokens=result.usage().input_tokens or 0,
                        output_tokens=result.usage().output_tokens or 0,
                        cost_usd=cost,
                        latency_ms=elapsed_ms,
                    )
                except Exception:
                    pass

            return result.output.confidence
        except Exception as e:
            logger.warning(f"[{deps.exchange_code}] Validation failed: {e}")
            return self._compute_confidence_from_fees(deps.extracted_fees)

    def _build_orchestrator_prompt(
        self,
        document: ExtractedDocument,
        exchange_code: str,
        sections: list | None = None,
        section_groups: list | None = None,
    ) -> str:
        """Build a compact prompt for the orchestrator with pre-computed section plan."""
        markdown = document.metadata.get("markdown")
        format_info = "Docling markdown" if markdown else "PDF/HTML text + tables"

        prompt_parts = [
            f"Extract all fee data from this {exchange_code} options exchange fee schedule.\n",
            f"Document format: {format_info}",
            f"Text length: {len(document.full_text)} chars",
            f"Tables: {len(document.tables)}",
        ]

        # Include pre-computed section plan — only groups, not individual sections
        if sections and section_groups:
            fee_count = sum(1 for s in sections if not s.is_context)
            ctx_count = sum(1 for s in sections if s.is_context)
            prompt_parts.append(
                f"\n== PRE-COMPUTED SECTION PLAN ==\n"
                f"Sections: {len(sections)} total ({fee_count} fee-bearing, {ctx_count} context)"
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
                prompt_parts.append(f"  Group {gi}: sections {global_indices} — {group.total_chars} chars — {headings}")

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

    def _compute_confidence_from_fees(self, raw_fees: list[dict]) -> float:
        """Fallback heuristic confidence if validator didn't run."""
        if not raw_fees:
            return 0.0

        score = 1.0
        participant_types = {f.get("participant_type") for f in raw_fees}
        fee_types = {f.get("fee_type") for f in raw_fees}

        if "CUSTOMER" not in participant_types:
            score -= 0.3
        if "MAKER" not in fee_types:
            score -= 0.2
        if "TAKER" not in fee_types:
            score -= 0.2
        if len(participant_types) < 2:
            score -= 0.15
        if len(raw_fees) < 4:
            score -= 0.2
        elif len(raw_fees) < 10:
            score -= 0.1

        return max(0.0, min(1.0, score))
