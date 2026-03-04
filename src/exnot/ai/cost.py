"""Per-run cost tracking with per-model pricing lookup."""

from __future__ import annotations

import logging
import time
from dataclasses import dataclass, field

from pydantic_ai.usage import RunUsage

logger = logging.getLogger(__name__)

# Per-model pricing: (input_cost_per_M_tokens, output_cost_per_M_tokens) in USD.
# Prefix-matched against the model name — more specific prefixes should come first.
# Prices sourced from OpenRouter / provider pricing pages.
MODEL_PRICING: dict[str, tuple[float, float]] = {
    # Qwen (DashScope direct / OpenRouter)
    "qwen/qwen3.5-flash": (0.10, 0.40),
    "qwen/qwen3.5-plus": (0.40, 2.40),
    "qwen/qwen3-235b": (0.55, 3.50),
    "qwen/qwen3-32b": (0.20, 0.60),
    "qwen/qwen3-30b": (0.20, 0.60),
    "qwen/qwen3-8b": (0.05, 0.20),
    "qwen/": (0.10, 0.40),  # Generic Qwen fallback (flash-tier)
    # DeepSeek
    "deepseek/deepseek-v3": (0.25, 0.40),
    "deepseek/deepseek-r1": (0.55, 2.19),
    "deepseek/": (0.25, 0.40),  # Generic DeepSeek fallback
    # Mistral
    "mistralai/mistral-small": (0.35, 0.56),
    "mistralai/mistral-large": (2.00, 6.00),
    "mistralai/mistral-medium": (2.75, 8.10),
    "mistralai/": (0.35, 0.56),  # Generic Mistral fallback (small-tier)
    # Anthropic (via OpenRouter)
    "anthropic/claude-sonnet-4": (3.00, 15.00),
    "anthropic/claude-3.5-sonnet": (3.00, 15.00),
    "anthropic/claude-3-haiku": (0.25, 1.25),
    "anthropic/": (3.00, 15.00),
    # Google (via OpenRouter)
    "google/gemini-2.5-flash": (0.15, 0.60),
    "google/gemini-2.5-pro": (1.25, 10.00),
    "google/gemini-2.0-flash": (0.10, 0.40),
    "google/": (0.15, 0.60),
    # OpenAI (via OpenRouter)
    "openai/gpt-4o": (2.50, 10.00),
    "openai/gpt-4o-mini": (0.15, 0.60),
    "openai/": (2.50, 10.00),
    # Meta Llama (via OpenRouter)
    "meta-llama/llama-4-maverick": (0.20, 0.60),
    "meta-llama/llama-4-scout": (0.15, 0.40),
    "meta-llama/": (0.20, 0.60),
}

# Conservative generic fallback for completely unknown models
_GENERIC_FALLBACK = (1.00, 3.00)


def _lookup_model_pricing(model: str) -> tuple[float, float]:
    """Look up per-token pricing for a model by prefix matching."""
    model_lower = model.lower()
    for prefix, pricing in MODEL_PRICING.items():
        if model_lower.startswith(prefix):
            return pricing
    return _GENERIC_FALLBACK


def _estimate_cost(model: str, input_tokens: int, output_tokens: int) -> float:
    """Estimate cost in USD using per-model pricing lookup.

    Tries LiteLLM first (may have the freshest data), then falls back to
    our built-in MODEL_PRICING table, then to a conservative generic rate.
    """
    try:
        from litellm import completion_cost

        cost = completion_cost(
            model=model,
            prompt_tokens=input_tokens,
            completion_tokens=output_tokens,
        )
        if cost > 0:
            return cost
    except Exception:
        pass

    input_rate, output_rate = _lookup_model_pricing(model)
    cost = (input_tokens * input_rate + output_tokens * output_rate) / 1_000_000

    if _lookup_model_pricing(model) is _GENERIC_FALLBACK:
        logger.warning(
            f"No pricing data for model '{model}', using generic fallback "
            f"(${input_rate}/M in, ${output_rate}/M out). "
            f"Add it to MODEL_PRICING in ai/cost.py for accurate tracking."
        )

    return cost


@dataclass
class CostTracker:
    """Tracks cost per exchange per pipeline run."""

    exchange_code: str
    budget_usd: float = 1.0
    total_cost_usd: float = 0.0
    calls: list[dict] = field(default_factory=list)
    _start_time: float = field(default_factory=time.time)

    def record(self, task: str, model: str, usage: RunUsage) -> float:
        """Record a completed AI call and return its cost."""
        input_tokens = usage.input_tokens or 0
        output_tokens = usage.output_tokens or 0
        cost = _estimate_cost(model, input_tokens, output_tokens)
        self.total_cost_usd += cost

        call_record = {
            "task": task,
            "model": model,
            "cost_usd": round(cost, 6),
            "input_tokens": input_tokens,
            "output_tokens": output_tokens,
        }
        self.calls.append(call_record)

        logger.info(
            f"[{self.exchange_code}] AI call: {task} ({model}) "
            f"${cost:.4f} ({input_tokens} in, {output_tokens} out) "
            f"total=${self.total_cost_usd:.4f}/{self.budget_usd:.2f}"
        )
        return cost

    @property
    def budget_remaining(self) -> float:
        return max(0.0, self.budget_usd - self.total_cost_usd)

    @property
    def is_over_budget(self) -> bool:
        return self.total_cost_usd >= self.budget_usd

    @property
    def total_input_tokens(self) -> int:
        return sum(c.get("input_tokens", 0) for c in self.calls)

    @property
    def total_output_tokens(self) -> int:
        return sum(c.get("output_tokens", 0) for c in self.calls)

    @property
    def total_tokens(self) -> int:
        return self.total_input_tokens + self.total_output_tokens

    def summary(self) -> dict:
        """Return a summary dict suitable for storing in snapshot.ai_extraction JSONB."""
        return {
            "extraction_mode": "AGENTIC",
            "total_cost_usd": round(self.total_cost_usd, 6),
            "budget_usd": self.budget_usd,
            "ai_calls_made": len(self.calls),
            "total_input_tokens": self.total_input_tokens,
            "total_output_tokens": self.total_output_tokens,
            "elapsed_seconds": round(time.time() - self._start_time, 1),
            "calls": self.calls,
        }
