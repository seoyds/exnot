"""Shared PydanticAI dependency dataclasses for all agents."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import TYPE_CHECKING

from exnot.ai.cost import CostTracker
from exnot.ai.models import ModelRegistry
from exnot.parser.base import ExtractedDocument

if TYPE_CHECKING:
    from exnot.ai.event_emitter import EventEmitter
    from exnot.parser.section_splitter import DocumentSection, SectionGroup


@dataclass
class ExtractionDeps:
    """Deps shared by all extraction-pipeline agents (orchestrator, extractor, validator, etc.)."""

    model_registry: ModelRegistry
    cost_tracker: CostTracker
    exchange_code: str
    exchange_hints: str = ""
    document: ExtractedDocument = field(default_factory=lambda: ExtractedDocument(full_text="", tables=[]))
    # Pre-computed sections and groups (set by AIExtractor before orchestrator runs)
    sections: list[DocumentSection] = field(default_factory=list)
    section_groups: list[SectionGroup] = field(default_factory=list)
    # Accumulator for extracted fees (stored here to avoid bloating orchestrator context)
    extracted_fees: list[dict] = field(default_factory=list)
    # Cache for table classifications (avoid repeated AI calls on orchestrator retry)
    table_classifications: list[dict] | None = None
    # Optional event emitter for monitoring pipeline progress
    event_emitter: EventEmitter | None = None


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
