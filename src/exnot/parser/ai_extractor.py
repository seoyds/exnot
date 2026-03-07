"""Extraction result dataclass used by normalizer and tools.

The original AIExtractor class (PydanticAI-based) has been removed.
Extraction is now handled by the Claude Agent SDK pipeline in exnot.agents.
This module retains only the ExtractionResult dataclass which is used by
the normalization engine and other downstream components.
"""

from dataclasses import dataclass, field


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
