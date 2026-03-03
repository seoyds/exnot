"""Tests for prompt integration into extraction pipeline."""

from exnot.ai.deps import ExtractionDeps


class TestExtractionDepsPromptField:
    def test_exchange_prompt_field_exists(self):
        """ExtractionDeps should have exchange_prompt field."""
        deps = ExtractionDeps.__dataclass_fields__
        assert "exchange_prompt" in deps

    def test_exchange_prompt_default_empty(self):
        """exchange_prompt should default to empty string."""
        from unittest.mock import MagicMock

        deps = ExtractionDeps(
            model_registry=MagicMock(),
            cost_tracker=MagicMock(),
            exchange_code="TEST",
        )
        assert deps.exchange_prompt == ""
