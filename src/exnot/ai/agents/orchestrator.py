"""Extraction orchestrator agent — CHEAP tier.

Plans and coordinates the extraction pipeline. Does NOT extract fees itself.
Has tools to: classify tables, get sections, extract per-section, validate, correct.
"""

from __future__ import annotations

import json
import logging

from pydantic_ai import Agent, ModelRetry, RunContext
from pydantic_ai.settings import ModelSettings

from exnot.ai.deps import ExtractionDeps
from exnot.ai.models import TaskType
from exnot.ai.types import OrchestratorResult

logger = logging.getLogger(__name__)

# Max table rows to send per table
MAX_TABLE_ROWS = 50

orchestrator_agent = Agent[ExtractionDeps, OrchestratorResult](
    "test",
    deps_type=ExtractionDeps,
    output_type=OrchestratorResult,
    instructions=(
        "You are coordinating the extraction of fee data from a US options exchange fee schedule.\n\n"
        "You have tools to:\n"
        "1. classify_tables — classify which tables contain transaction fees\n"
        "2. get_document_sections — split the document into logical sections\n"
        "3. extract_section — extract fees from a section (calls an expensive AI model)\n"
        "4. validate_extraction — validate ALL accumulated fees for completeness\n"
        "5. correct_extraction — fix issues found by validation (expensive, budget-gated)\n\n"
        "STRATEGY:\n"
        "- The document has been PRE-SPLIT into section groups. The prompt includes the section plan.\n"
        "- You MUST call extract_section ONCE for EACH group listed in the plan.\n"
        "- Do NOT combine groups or pass all section indices in a single call.\n"
        "- Do NOT skip any fee-bearing groups.\n"
        "- extract_section stores fees internally and returns a count summary.\n"
        "- After all groups are extracted, call validate_extraction (no arguments needed).\n"
        "- If validation finds issues and budget allows, call correct_extraction with the issues.\n"
        "- For your final output, set fees=[] — the system uses the internally stored fees.\n"
    ),
    retries=4,
)


@orchestrator_agent.tool
async def classify_tables(ctx: RunContext[ExtractionDeps]) -> list[dict]:
    """Classify document tables as fee-relevant or not. Returns classification for each table."""
    from exnot.ai.agents.table_classifier import classify_tables_hybrid

    tables = ctx.deps.document.tables
    if not tables:
        return [{"message": "No tables in document"}]

    classifications = await classify_tables_hybrid(tables, deps=ctx.deps)
    return [c.model_dump() for c in classifications]


@orchestrator_agent.tool
async def get_document_sections(ctx: RunContext[ExtractionDeps]) -> list[dict]:
    """Split document into logical sections. Returns section headings and char counts."""
    # Use pre-computed sections from deps (set by AIExtractor) or split on-demand
    if ctx.deps.sections:
        sections = ctx.deps.sections
    else:
        from exnot.parser.section_splitter import (
            classify_context_sections,
            split_document,
        )

        document = ctx.deps.document
        format_hint = document.metadata.get("parser", "pdf")
        sections = split_document(document, format_hint=format_hint)
        sections = classify_context_sections(sections)

    return [
        {
            "index": i,
            "heading": s.heading[:100],
            "char_count": s.char_count,
            "table_count": len(s.tables),
            "is_context": s.is_context,
        }
        for i, s in enumerate(sections)
    ]


@orchestrator_agent.tool
async def extract_section(
    ctx: RunContext[ExtractionDeps],
    section_indices: list[int],
    section_info: str,
) -> dict:
    """Extract fees from specified section(s). Pass section indices from get_document_sections.

    Args:
        section_indices: List of section indices to extract from.
        section_info: Brief description of what sections are being extracted.
    """
    from exnot.ai.agents.section_extractor import section_extractor_agent

    # Use pre-computed sections from deps (set by AIExtractor) or split on-demand
    if ctx.deps.sections:
        all_sections = ctx.deps.sections
    else:
        from exnot.parser.section_splitter import (
            classify_context_sections,
            split_document,
        )

        document = ctx.deps.document
        format_hint = document.metadata.get("parser", "pdf")
        all_sections = split_document(document, format_hint=format_hint)
        all_sections = classify_context_sections(all_sections)

    context_sections = [s for s in all_sections if s.is_context]

    # Build context text from definitions/footnotes
    context_parts: list[str] = []
    for s in context_sections:
        context_parts.append(f"--- {s.heading} ---")
        context_parts.append(s.text[:3000])
        for table in s.tables[:3]:
            context_parts.append(f"Table: {table.title}")
            context_parts.append(f"Headers: {table.headers}")
            for row in table.rows[:20]:
                context_parts.append(f"  {row}")
    context_text = "\n".join(context_parts)[:8000]

    # Gather the requested sections
    target_sections = [all_sections[i] for i in section_indices if i < len(all_sections)]
    if not target_sections:
        return {"fees": [], "extraction_notes": "No valid sections found"}

    # Hard cap: refuse calls that would send too much content to the extractor
    from exnot.config import get_settings

    char_budget = get_settings().ai_section_char_budget
    total_chars = sum(s.char_count for s in target_sections)
    max_allowed = char_budget * 3  # 3x budget as hard ceiling
    if total_chars > max_allowed:
        logger.warning(
            f"[{ctx.deps.exchange_code}] extract_section refused: "
            f"{total_chars} chars > {max_allowed} max for indices {section_indices}"
        )
        return {
            "fees": [],
            "extraction_notes": (
                f"REFUSED: Combined section content ({total_chars} chars) exceeds "
                f"maximum ({max_allowed} chars). Call extract_section with fewer "
                f"sections — use the pre-computed groups from the section plan."
            ),
        }

    # Build section content
    section_text_parts: list[str] = []
    section_tables_parts: list[str] = []
    from exnot.parser.table_classifier import classify_tables as rule_classify_tables

    for section in target_sections:
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

    section_data = "\n".join(section_text_parts)
    tables_data = "\n".join(section_tables_parts)

    prompt_parts = [f"Extract fees from: {section_info}"]
    prompt_parts.append(f"\nSECTION DATA:\n{section_data}")
    if tables_data:
        prompt_parts.append(f"\nSECTION TABLES:\n{tables_data}")
    if context_text:
        prompt_parts.append(f"\nREFERENCE CONTEXT (definitions, footnotes, glossary):\n{context_text}")

    # Add exchange-specific hints
    if ctx.deps.exchange_hints:
        prompt_parts.append(f"\n{ctx.deps.exchange_hints}")

    prompt = "\n".join(prompt_parts)

    # Call the section extractor agent
    model = ctx.deps.model_registry.get_model(TaskType.FEE_EXTRACTION)
    result = await section_extractor_agent.run(
        prompt,
        deps=ctx.deps,
        model=model,
        usage=ctx.usage,
        model_settings=ModelSettings(max_tokens=16384),
    )

    # Track cost
    model_name = ctx.deps.model_registry.get_model_name(TaskType.FEE_EXTRACTION)
    ctx.deps.cost_tracker.record(
        task=f"extract_section:{section_info[:50]}",
        model=model_name,
        usage=result.usage(),
    )

    # Store full results in deps (avoids bloating orchestrator conversation context)
    output = result.output
    fee_dicts = [f.model_dump() for f in output.fees]
    ctx.deps.extracted_fees.extend(fee_dicts)

    # Return only a compact summary to the orchestrator
    return {
        "fees_extracted": len(output.fees),
        "extraction_notes": output.extraction_notes or "",
        "total_fees_so_far": len(ctx.deps.extracted_fees),
    }


@orchestrator_agent.tool
async def validate_extraction(
    ctx: RunContext[ExtractionDeps],
) -> dict:
    """Validate all extracted fees for completeness and correctness.

    Uses the accumulated fees from all previous extract_section calls.
    IMPORTANT: Only call AFTER extracting ALL groups via extract_section.
    """
    if not ctx.deps.extracted_fees:
        return {
            "is_valid": False,
            "confidence": 0.0,
            "issues": [{"severity": "ERROR", "message": "No fees extracted yet. Call extract_section first."}],
            "suggested_actions": ["Call extract_section for each group in the section plan before validating."],
        }

    from exnot.ai.agents.fee_validator import fee_validator_agent

    fees_json = json.dumps(ctx.deps.extracted_fees)
    prompt = (
        f"Validate these extracted fees for {ctx.deps.exchange_code}.\n\n"
        f"Extracted fees ({len(ctx.deps.extracted_fees)} entries):\n{fees_json}\n"
    )

    model = ctx.deps.model_registry.get_model(TaskType.FEE_VALIDATION)
    result = await fee_validator_agent.run(
        prompt,
        deps=ctx.deps,
        model=model,
        usage=ctx.usage,
        model_settings=ModelSettings(max_tokens=8192),
    )

    model_name = ctx.deps.model_registry.get_model_name(TaskType.FEE_VALIDATION)
    ctx.deps.cost_tracker.record(
        task="validate_extraction",
        model=model_name,
        usage=result.usage(),
    )

    return result.output.model_dump()


@orchestrator_agent.tool
async def correct_extraction(
    ctx: RunContext[ExtractionDeps],
    issues_description: str,
) -> dict:
    """Fix specific issues in previously extracted fees. Budget-gated — only call if validation found issues.

    Uses the accumulated fees from deps. Pass the issues description from validation.

    Args:
        issues_description: Description of the specific issues to fix.
    """
    from exnot.ai.agents.correction import correction_agent

    if ctx.deps.cost_tracker.is_over_budget:
        return {
            "corrections": [],
            "removed_indices": [],
            "confidence": 0.0,
            "notes": "Skipped — over budget",
        }

    # Build context from document
    doc = ctx.deps.document
    doc_context = doc.full_text[:30000]
    fees_json = json.dumps(ctx.deps.extracted_fees)

    prompt = (
        f"Previous extraction for {ctx.deps.exchange_code}:\n"
        f"{fees_json}\n\n"
        f"Issues identified:\n{issues_description}\n\n"
        f"Document context:\n{doc_context}\n"
    )

    if ctx.deps.exchange_hints:
        prompt += f"\n{ctx.deps.exchange_hints}\n"

    model = ctx.deps.model_registry.get_model(TaskType.CORRECTION)
    result = await correction_agent.run(
        prompt,
        deps=ctx.deps,
        model=model,
        usage=ctx.usage,
        model_settings=ModelSettings(max_tokens=16384),
    )

    model_name = ctx.deps.model_registry.get_model_name(TaskType.CORRECTION)
    ctx.deps.cost_tracker.record(
        task="correct_extraction",
        model=model_name,
        usage=result.usage(),
    )

    return result.output.model_dump()


@orchestrator_agent.output_validator
async def validate_orchestrator_output(
    ctx: RunContext[ExtractionDeps], output: OrchestratorResult
) -> OrchestratorResult:
    """Validate extraction and populate output from accumulated fees in deps."""
    # Fees are stored in deps.extracted_fees, not in output.fees
    accumulated = ctx.deps.extracted_fees
    if not accumulated:
        raise ModelRetry(
            "No fees extracted. You must call extract_section on at least one section. "
            "Call extract_section for EACH group in the section plan."
        )

    # Check that enough groups were extracted (at least half of expected groups)
    expected_groups = len(ctx.deps.section_groups)
    if expected_groups > 1 and len(accumulated) < 5:
        raise ModelRetry(
            f"Only {len(accumulated)} fees extracted from {expected_groups} groups — "
            f"this is too few. You must call extract_section for EACH group listed "
            f"in the section plan. Do NOT skip groups."
        )

    # Check for minimum fee variety
    participant_types = {f.get("participant_type") for f in accumulated}
    fee_types = {f.get("fee_type") for f in accumulated}
    issues: list[str] = []

    if "CUSTOMER" not in participant_types and len(accumulated) > 5:
        issues.append(
            "Missing CUSTOMER fees — most exchanges have Customer/Retail fees. "
            "Check if the document uses 'Priority Customer' or 'Public Customer'."
        )

    if "MAKER" not in fee_types and "TAKER" not in fee_types and len(accumulated) > 5:
        issues.append(
            "Missing both MAKER and TAKER fees — most exchanges have maker/taker pricing."
        )

    if issues:
        raise ModelRetry(
            "Extraction may be incomplete:\n" + "\n".join(issues) + "\n"
            "Call extract_section on additional sections or call correct_extraction."
        )

    return output
