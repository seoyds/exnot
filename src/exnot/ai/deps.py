"""Shared PydanticAI dependency dataclasses for all agents."""

from __future__ import annotations

from dataclasses import dataclass, field

from exnot.ai.cost import CostTracker
from exnot.ai.models import ModelRegistry
from exnot.parser.base import ExtractedDocument


@dataclass
class ExtractionDeps:
    """Deps shared by all extraction-pipeline agents (orchestrator, extractor, validator, etc.)."""

    model_registry: ModelRegistry
    cost_tracker: CostTracker
    exchange_code: str
    exchange_hints: str = ""
    document: ExtractedDocument = field(default_factory=lambda: ExtractedDocument(full_text="", tables=[]))


@dataclass
class DiscoveryDeps:
    """Deps for the URL discovery agent."""

    model_registry: ModelRegistry
    cost_tracker: CostTracker
    exchange_code: str
    exchange_name: str = ""
    operator: str = ""


@dataclass
class SummaryDeps:
    """Deps for the change summary agent."""

    model_registry: ModelRegistry
    cost_tracker: CostTracker
    exchange_code: str
