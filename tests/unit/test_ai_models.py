"""Tests for AI model registry."""

from unittest.mock import MagicMock

from exnot.ai.models import ModelRegistry, TaskType


def _make_settings(**overrides):
    """Create a mock Settings with defaults."""
    settings = MagicMock()
    settings.openrouter_api_key = "test-key"
    settings.openrouter_base_url = "https://openrouter.ai/api/v1"
    settings.ai_model = "deepseek/deepseek-v3.2-20251201"
    settings.ai_model_table_classification = "deepseek/deepseek-v3.2-20251201"
    settings.ai_model_orchestrator = "deepseek/deepseek-v3.2-20251201"
    settings.ai_model_fee_extraction = "deepseek/deepseek-v3.2-20251201"
    settings.ai_model_fee_validation = "deepseek/deepseek-v3.2-20251201"
    settings.ai_model_correction = "deepseek/deepseek-v3.2-20251201"
    settings.ai_model_url_discovery = "deepseek/deepseek-v3.2-20251201"
    settings.ai_model_change_summary = "deepseek/deepseek-v3.2-20251201"
    for k, v in overrides.items():
        setattr(settings, k, v)
    return settings


class TestModelRegistry:
    def test_get_model_name_per_task(self):
        settings = _make_settings()
        registry = ModelRegistry(settings)

        assert registry.get_model_name(TaskType.TABLE_CLASSIFICATION) == "deepseek/deepseek-v3.2-20251201"
        assert registry.get_model_name(TaskType.FEE_EXTRACTION) == "deepseek/deepseek-v3.2-20251201"
        assert registry.get_model_name(TaskType.FEE_VALIDATION) == "deepseek/deepseek-v3.2-20251201"

    def test_get_model_returns_instance(self):
        settings = _make_settings()
        registry = ModelRegistry(settings)

        model = registry.get_model(TaskType.ORCHESTRATOR)
        assert model is not None

    def test_model_caching(self):
        settings = _make_settings()
        registry = ModelRegistry(settings)

        model1 = registry.get_model(TaskType.ORCHESTRATOR)
        model2 = registry.get_model(TaskType.TABLE_CLASSIFICATION)

        # Same model name -> same cached instance
        assert model1 is model2

    def test_different_models_not_shared(self):
        settings = _make_settings(ai_model_fee_extraction="anthropic/claude-sonnet-4-20250514")
        registry = ModelRegistry(settings)

        cheap = registry.get_model(TaskType.ORCHESTRATOR)  # deepseek
        expensive = registry.get_model(TaskType.FEE_EXTRACTION)  # claude-sonnet

        assert cheap is not expensive

    def test_custom_model_override(self):
        settings = _make_settings(ai_model_orchestrator="custom/my-model")
        registry = ModelRegistry(settings)

        assert registry.get_model_name(TaskType.ORCHESTRATOR) == "custom/my-model"
