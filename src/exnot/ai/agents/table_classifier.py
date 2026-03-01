"""Hybrid table classifier — rule-based first, AI fallback for ambiguous tables.

Uses the existing rule-based classifier from parser/table_classifier.py.
Only calls AI (CHEAP tier) for tables with scores near zero (ambiguous).
"""

from __future__ import annotations

import logging

from pydantic_ai import Agent, ToolOutput
from pydantic_ai.settings import ModelSettings

from exnot.ai.deps import ExtractionDeps
from exnot.ai.types import TableClassification
from exnot.parser.base import ExtractedTable
from exnot.parser.table_classifier import classify_table as rule_classify

logger = logging.getLogger(__name__)

# AI agent for ambiguous tables only
ai_classifier_agent = Agent[None, TableClassification](
    "test",
    output_type=ToolOutput(TableClassification, name="return_classification"),
    instructions=(
        "You classify tables from US options exchange fee schedules.\n"
        "Determine if the table contains per-contract transaction fees/rebates.\n\n"
        "FEE_TRANSACTION: Contains maker/taker fees, rebates, per-contract amounts.\n"
        "DEFINITIONS: Contains definitions, acronyms, glossary terms.\n"
        "CONNECTIVITY: Contains port fees, connectivity fees, monthly flat fees.\n"
        "OTHER: None of the above.\n\n"
        "A table IS a fee table if it has dollar amounts ($0.XX) and participant types "
        "(Customer, Market Maker, etc.) or fee types (Maker, Taker).\n"
    ),
    retries=1,
)


async def classify_tables_hybrid(
    tables: list[ExtractedTable],
    deps: ExtractionDeps | None = None,
) -> list[TableClassification]:
    """Classify tables using rules first, AI only for ambiguous ones.

    Args:
        tables: The tables to classify.
        deps: Extraction deps (needed for AI fallback). If None, rule-only.

    Returns:
        List of TableClassification for each table.
    """
    results: list[TableClassification] = []

    for i, table in enumerate(tables):
        rule_result = rule_classify(table, i)

        # Clear-cut: score >= 2 (definitely fee) or score <= -2 (definitely not)
        if abs(rule_result.score) >= 2:
            results.append(TableClassification(
                table_index=i,
                is_fee_table=rule_result.is_fee_table,
                table_type="FEE_TRANSACTION" if rule_result.is_fee_table else "OTHER",
                confidence=1.0,
                reasoning=f"Rule-based: {rule_result.reason}",
            ))
            continue

        # Ambiguous (score is -1, 0, or 1): use AI if available
        if deps is not None and not deps.cost_tracker.is_over_budget:
            ai_result = await _classify_with_ai(table, i, deps)
            if ai_result is not None:
                results.append(ai_result)
                continue

        # Fallback to rule-based result
        results.append(TableClassification(
            table_index=i,
            is_fee_table=rule_result.is_fee_table,
            table_type="FEE_TRANSACTION" if rule_result.is_fee_table else "OTHER",
            confidence=0.5,
            reasoning=f"Rule-based (ambiguous): {rule_result.reason}",
        ))

    return results


async def _classify_with_ai(
    table: ExtractedTable,
    table_index: int,
    deps: ExtractionDeps,
) -> TableClassification | None:
    """Use AI to classify an ambiguous table."""
    from exnot.ai.models import TaskType

    # Build compact table representation (truncate cells to avoid token bloat)
    headers = " | ".join(h[:100] for h in table.headers[:15]) if table.headers else "(no headers)"
    sample_rows = "\n".join(
        " | ".join(str(c)[:200] for c in row[:15])
        for row in table.rows[:3]
    )
    prompt = (
        f"Classify this table (index {table_index}):\n"
        f"Title: {table.title or '(untitled)'}\n"
        f"Headers: {headers}\n"
        f"Sample rows:\n{sample_rows}\n"
    )

    try:
        model = deps.model_registry.get_model(TaskType.TABLE_CLASSIFICATION)
        result = await ai_classifier_agent.run(
            prompt,
            model=model,
            model_settings=ModelSettings(max_tokens=4096),
        )

        # Track cost
        model_name = deps.model_registry.get_model_name(TaskType.TABLE_CLASSIFICATION)
        deps.cost_tracker.record(
            task=f"table_classification_{table_index}",
            model=model_name,
            usage=result.usage(),
        )

        output = result.output
        output.table_index = table_index
        return output
    except Exception as e:
        logger.warning(f"AI table classification failed for table {table_index}: {e}")
        return None
