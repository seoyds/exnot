"""Tests for the per-exchange prompt registry."""

import pytest

from exnot.ai.prompts.registry import EXCHANGE_PROMPTS, get_extraction_prompt


class TestPromptRegistry:
    def test_get_prompt_for_known_exchange(self):
        prompt = get_extraction_prompt("CBOE_BZX")
        assert "EXCHANGE: Cboe BZX" in prompt
        assert "origin_code" in prompt
        assert "TERMINOLOGY MAPPING" in prompt

    def test_get_prompt_for_all_exchanges(self):
        """Every exchange in the registry should return a non-empty prompt."""
        expected_exchanges = [
            "CBOE_BZX",
            "CBOE_EDGX",
            "CBOE_C1",
            "CBOE_C2",
            "NASDAQ_ISE",
            "NASDAQ_NOM",
            "NASDAQ_PHLX",
            "NASDAQ_GEMX",
            "NASDAQ_MRX",
            "NASDAQ_BX",
            "MIAX_OPTIONS",
            "MIAX_PEARL",
            "MIAX_EMERALD",
            "MIAX_SAPPHIRE",
            "NYSE_ARCA",
            "NYSE_AMERICAN",
            "BOX_OPTIONS",
            "MEMX_OPTIONS",
        ]
        for code in expected_exchanges:
            prompt = get_extraction_prompt(code)
            assert len(prompt) > 200, f"Prompt for {code} is too short"
            assert "EXCHANGE:" in prompt

    def test_unknown_exchange_falls_back_to_base(self):
        prompt = get_extraction_prompt("UNKNOWN_EX")
        assert "origin_code" in prompt  # Base prompt content
        assert "EXCHANGE:" not in prompt  # No exchange-specific section

    def test_prompt_contains_base(self):
        """Every prompt should include the base schema/rules."""
        prompt = get_extraction_prompt("CBOE_BZX")
        assert "origin_code" in prompt
        assert "fee_value" in prompt
        assert "REBATE" in prompt.upper() or "rebate" in prompt

    def test_prompt_count(self):
        assert len(EXCHANGE_PROMPTS) == 18
