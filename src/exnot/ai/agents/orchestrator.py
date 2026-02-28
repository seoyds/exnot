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
        "4. validate_extraction — validate extracted fees for completeness\n"
        "5. correct_extraction — fix issues found by validation (expensive, budget-gated)\n\n"
        "STRATEGY:\n"
        "- First call get_document_sections to understand document structure.\n"
        "- For small documents (1-2 sections), call extract_section once with the full content.\n"
        "- For large documents, call extract_section for each section group.\n"
        "- After extraction, call validate_extraction to check completeness.\n"
        "- If validation finds issues and budget allows, call correct_extraction.\n"
        "- Return the final merged result.\n\n"
        "IMPORTANT: Your final output should contain ALL extracted fees merged and deduplicated.\n"
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
    from exnot.parser.section_splitter import (
        classify_context_sections,
        split_document,
    )

    document = ctx.deps.document
    format_hint = document.metadata.get("parser", "pdf")

    sections = split_document(document, format_hint=format_hint)
    sections = classify_context_sections(sections)

    context_sections = [s for s in sections if s.is_context]
    all_sections = sections

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

    return result.output.model_dump()


@orchestrator_agent.tool
async def validate_extraction(
    ctx: RunContext[ExtractionDeps],
    fees_json: str,
) -> dict:
    """Validate extracted fees for completeness and correctness.

    Args:
        fees_json: JSON string of the extracted fees array.
    """
    from exnot.ai.agents.fee_validator import fee_validator_agent

    prompt = (
        f"Validate these extracted fees for {ctx.deps.exchange_code}.\n\n"
        f"Extracted fees ({len(json.loads(fees_json))} entries):\n{fees_json}\n"
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
    previous_fees_json: str,
    issues_description: str,
) -> dict:
    """Fix specific issues in previously extracted fees. Budget-gated — only call if validation found issues.

    Args:
        previous_fees_json: JSON string of the previously extracted fees.
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

    prompt = (
        f"Previous extraction for {ctx.deps.exchange_code}:\n"
        f"{previous_fees_json}\n\n"
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
    """Validate the orchestrator's final output for basic completeness."""
    issues: list[str] = []

    if not output.fees:
        raise ModelRetry(
            "No fees extracted. You must call extract_section on at least one section. "
            "Call get_document_sections first, then extract_section."
        )

    # Check for minimum fee variety
    participant_types = {f.participant_type for f in output.fees}
    fee_types = {f.fee_type for f in output.fees}

    if "CUSTOMER" not in participant_types and len(output.fees) > 5:
        issues.append(
            "Missing CUSTOMER fees — most exchanges have Customer/Retail fees. "
            "Check if the document uses 'Priority Customer' or 'Public Customer'."
        )

    if "MAKER" not in fee_types and "TAKER" not in fee_types and len(output.fees) > 5:
        issues.append(
            "Missing both MAKER and TAKER fees — most exchanges have maker/taker pricing."
        )

    if issues:
        raise ModelRetry(
            "Extraction may be incomplete:\n" + "\n".join(issues) + "\n"
            "Call extract_section on additional sections or call correct_extraction."
        )

    return output
