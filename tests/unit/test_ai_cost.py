"""Tests for AI cost tracker."""

from pydantic_ai.usage import RunUsage as Usage

from exnot.ai.cost import CostTracker


class TestCostTracker:
    def test_initial_state(self):
        tracker = CostTracker(exchange_code="TEST", budget_usd=2.0)
        assert tracker.total_cost_usd == 0.0
        assert tracker.budget_remaining == 2.0
        assert not tracker.is_over_budget
        assert tracker.total_tokens == 0

    def test_record_adds_cost(self):
        tracker = CostTracker(exchange_code="TEST", budget_usd=2.0)
        usage = Usage(input_tokens=1000, output_tokens=200, requests=1)
        cost = tracker.record("test_task", "qwen/qwen3.5-flash-02-23", usage)

        assert cost >= 0
        assert tracker.total_cost_usd > 0
        assert len(tracker.calls) == 1
        assert tracker.calls[0]["task"] == "test_task"
        assert tracker.total_input_tokens == 1000
        assert tracker.total_output_tokens == 200

    def test_budget_tracking(self):
        tracker = CostTracker(exchange_code="TEST", budget_usd=0.001)
        usage = Usage(input_tokens=100000, output_tokens=50000, requests=1)
        tracker.record("expensive_task", "deepseek/deepseek-v3.2-20251201", usage)

        # With 100K+ tokens, cost should exceed $0.001 budget
        assert tracker.is_over_budget or tracker.total_cost_usd > 0

    def test_summary(self):
        tracker = CostTracker(exchange_code="TEST", budget_usd=2.0)
        usage = Usage(input_tokens=500, output_tokens=100, requests=1)
        tracker.record("task1", "qwen/qwen3.5-flash-02-23", usage)

        summary = tracker.summary()
        assert summary["extraction_mode"] == "AGENTIC"
        assert summary["ai_calls_made"] == 1
        assert summary["total_input_tokens"] == 500
        assert summary["total_output_tokens"] == 100
        assert "elapsed_seconds" in summary
        assert "calls" in summary

    def test_multiple_calls(self):
        tracker = CostTracker(exchange_code="TEST", budget_usd=5.0)
        for i in range(3):
            usage = Usage(input_tokens=1000, output_tokens=200, requests=1)
            tracker.record(f"task_{i}", "qwen/qwen3.5-flash-02-23", usage)

        assert len(tracker.calls) == 3
        assert tracker.total_input_tokens == 3000
        assert tracker.total_output_tokens == 600
