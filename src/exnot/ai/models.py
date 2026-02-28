"""LiteLLM model registry with per-task routing via PydanticAI."""

from __future__ import annotations

import logging
from enum import Enum
from functools import lru_cache

from pydantic_ai.models.openai import OpenAIChatModel
from pydantic_ai.profiles.openai import OpenAIModelProfile
from pydantic_ai.providers.openai import OpenAIProvider

from exnot.config import Settings, get_settings

logger = logging.getLogger(__name__)


class TaskType(str, Enum):
    """AI task types, each mapped to a specific model tier."""

    TABLE_CLASSIFICATION = "table_classification"
    ORCHESTRATOR = "orchestrator"
    FEE_EXTRACTION = "fee_extraction"
    FEE_VALIDATION = "fee_validation"
    CORRECTION = "correction"
    URL_DISCOVERY = "url_discovery"
    CHANGE_SUMMARY = "change_summary"


# Maps TaskType -> Settings attribute name for per-task model config
_TASK_MODEL_ATTRS: dict[TaskType, str] = {
    TaskType.TABLE_CLASSIFICATION: "ai_model_table_classification",
    TaskType.ORCHESTRATOR: "ai_model_orchestrator",
    TaskType.FEE_EXTRACTION: "ai_model_fee_extraction",
    TaskType.FEE_VALIDATION: "ai_model_fee_validation",
    TaskType.CORRECTION: "ai_model_correction",
    TaskType.URL_DISCOVERY: "ai_model_url_discovery",
    TaskType.CHANGE_SUMMARY: "ai_model_change_summary",
}


class ModelRegistry:
    """Resolves TaskType -> PydanticAI model instance via OpenRouter."""

    def __init__(self, settings: Settings | None = None):
        self._settings = settings or get_settings()
        self._provider = OpenAIProvider(
            base_url=self._settings.openrouter_base_url,
            api_key=self._settings.openrouter_api_key,
        )
        self._cache: dict[str, OpenAIChatModel] = {}

    def get_model_name(self, task: TaskType) -> str:
        """Get the model ID string for a task, falling back to default ai_model."""
        attr = _TASK_MODEL_ATTRS.get(task)
        if attr:
            return getattr(self._settings, attr, self._settings.ai_model)
        return self._settings.ai_model

    def get_model(self, task: TaskType) -> OpenAIChatModel:
        """Get or create a PydanticAI model instance for the given task."""
        model_name = self.get_model_name(task)
        if model_name not in self._cache:
            self._cache[model_name] = OpenAIChatModel(
                model_name,
                provider=self._provider,
                profile=OpenAIModelProfile(
                    openai_supports_strict_tool_definition=False,
                ),
            )
            logger.debug(f"Created model instance for {task.value}: {model_name}")
        return self._cache[model_name]


@lru_cache
def get_model_registry() -> ModelRegistry:
    """Get the singleton ModelRegistry instance."""
    return ModelRegistry()
