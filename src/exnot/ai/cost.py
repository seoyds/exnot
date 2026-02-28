"""Per-run cost tracking using LiteLLM's completion_cost()."""

from __future__ import annotations

import logging
import time
from dataclasses import dataclass, field

from pydantic_ai.usage import RunUsage

logger = logging.getLogger(__name__)


def _estimate_cost(model: str, input_tokens: int, output_tokens: int) -> float:
    """Estimate cost in USD using LiteLLM's cost database."""
    try:
        from litellm import completion_cost

        return completion_cost(
            model=model,
            prompt_tokens=input_tokens,
            completion_tokens=output_tokens,
        )
    except Exception:
        # Fallback: rough estimate at $3/M input, $15/M output (Claude Sonnet tier)
        return (input_tokens * 3.0 + output_tokens * 15.0) / 1_000_000


@dataclass
class CostTracker:
    """Tracks cost per exchange per pipeline run."""

    exchange_code: str
    budget_usd: float = 2.0
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
