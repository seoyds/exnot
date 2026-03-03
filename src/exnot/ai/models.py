"""Model registry with per-task routing via PydanticAI.

Supports direct provider APIs (DashScope for Qwen) with OpenRouter as fallback.
"""

from __future__ import annotations

import logging
from enum import Enum
from functools import lru_cache

from pydantic_ai.models.openai import OpenAIChatModel
from pydantic_ai.providers.openai import OpenAIProvider
from pydantic_ai.providers.openrouter import OpenRouterProvider
from pydantic_ai.settings import ModelSettings

from exnot.config import Settings, get_settings

logger = logging.getLogger(__name__)

DASHSCOPE_BASE_URL = "https://dashscope-intl.aliyuncs.com/compatible-mode/v1"


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
    """Resolves TaskType -> PydanticAI model instance.

    Routes to direct providers when API keys are configured,
    falls back to OpenRouter otherwise.
    """

    def __init__(self, settings: Settings | None = None):
        self._settings = settings or get_settings()
        self._openrouter_provider = OpenRouterProvider(
            api_key=self._settings.openrouter_api_key,
        )
        self._dashscope_provider: OpenAIProvider | None = None
        if self._settings.dashscope_api_key:
            self._dashscope_provider = OpenAIProvider(
                base_url=DASHSCOPE_BASE_URL,
                api_key=self._settings.dashscope_api_key,
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
            provider, provider_name, api_model_name = self._resolve_provider(model_name)
            self._cache[model_name] = OpenAIChatModel(
                api_model_name,
                provider=provider,
            )
            logger.info(f"Created model for {task.value}: {model_name} via {provider_name}")
        return self._cache[model_name]

    def get_model_settings(self, task: TaskType, **overrides) -> ModelSettings:
        """Get ModelSettings for a task, with provider-specific defaults."""
        model_name = self.get_model_name(task)
        settings: dict = {}
        # DashScope Qwen models need thinking mode disabled for tool_choice to work
        if model_name.startswith("qwen/") and self._dashscope_provider:
            settings["extra_body"] = {"enable_thinking": False}
        settings.update(overrides)
        return ModelSettings(**settings)

    def _resolve_provider(self, model_name: str) -> tuple:
        """Resolve model name to (provider, provider_label, api_model_name)."""
        # Qwen models → DashScope direct (when API key is set)
        if model_name.startswith("qwen/") and self._dashscope_provider:
            api_name = model_name.removeprefix("qwen/")
            return self._dashscope_provider, "DashScope", api_name

        # Default: OpenRouter
        return self._openrouter_provider, "OpenRouter", model_name


@lru_cache
def get_model_registry() -> ModelRegistry:
    """Get the singleton ModelRegistry instance."""
    return ModelRegistry()
