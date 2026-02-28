"""Generate human-readable change reports, optionally AI-enhanced."""

import json
import logging

from exnot.differ.detector import ChangeReport

logger = logging.getLogger(__name__)


class ChangeReporter:
    """Generates formatted change reports."""

    def generate_text_report(self, report: ChangeReport) -> str:
        """Generate a plain text change report."""
        lines = [
            f"Fee Schedule Change Report: {report.exchange_code}",
            f"Version: {report.old_version or 'N/A'} → {report.new_version}",
            f"Summary: {report.summary}",
            "",
        ]

        if not report.has_changes:
            lines.append("No changes detected.")
            return "\n".join(lines)

        if report.modified_count:
            lines.append("=== MODIFIED FEES ===")
            for c in report.changes:
                if c.change_type == "MODIFIED":
                    old = f"${c.old_amount_cents / 10000:.4f}" if c.old_amount_cents is not None else "N/A"
                    new = f"${c.new_amount_cents / 10000:.4f}" if c.new_amount_cents is not None else "N/A"
                    lines.append(
                        f"  {c.participant_type} | {c.security_class} | {c.fee_type}: "
                        f"{old} → {new}"
                    )
            lines.append("")

        if report.new_count:
            lines.append("=== NEW FEES ===")
            for c in report.changes:
                if c.change_type == "NEW":
                    amt = f"${c.new_amount_cents / 10000:.4f}" if c.new_amount_cents is not None else "N/A"
                    lines.append(
                        f"  {c.participant_type} | {c.security_class} | {c.fee_type}: {amt}"
                    )
            lines.append("")

        if report.removed_count:
            lines.append("=== REMOVED FEES ===")
            for c in report.changes:
                if c.change_type == "REMOVED":
                    amt = f"${c.old_amount_cents / 10000:.4f}" if c.old_amount_cents is not None else "N/A"
                    lines.append(
                        f"  {c.participant_type} | {c.security_class} | {c.fee_type}: {amt}"
                    )

        return "\n".join(lines)

    def generate_ai_summary(self, report: ChangeReport) -> str:
        """Generate an AI-enhanced natural language summary using the summarizer agent."""
        if not report.has_changes:
            return report.summary

        try:
            import asyncio

            from exnot.ai.agents.summarizer import summarizer_agent
            from exnot.ai.cost import CostTracker
            from exnot.ai.deps import SummaryDeps
            from exnot.ai.models import ModelRegistry, TaskType
            from exnot.config import get_settings

            settings = get_settings()

            changes_json = json.dumps(
                [
                    {
                        "type": c.change_type,
                        "participant": c.participant_type,
                        "security": c.security_class,
                        "fee_type": c.fee_type,
                        "old_amount": f"${c.old_amount_cents / 10000:.4f}" if c.old_amount_cents else None,
                        "new_amount": f"${c.new_amount_cents / 10000:.4f}" if c.new_amount_cents else None,
                    }
                    for c in report.changes[:30]  # Compact: limit to 30 changes
                ],
                indent=2,
            )

            prompt = (
                f"Summarize these fee schedule changes for {report.exchange_code}.\n\n"
                f"Changes:\n{changes_json}"
            )

            registry = ModelRegistry(settings)
            cost_tracker = CostTracker(exchange_code=report.exchange_code, budget_usd=0.50)
            deps = SummaryDeps(
                model_registry=registry,
                cost_tracker=cost_tracker,
                exchange_code=report.exchange_code,
            )

            model = registry.get_model(TaskType.CHANGE_SUMMARY)

            async def _run():
                result = await summarizer_agent.run(prompt, deps=deps, model=model)
                model_name = registry.get_model_name(TaskType.CHANGE_SUMMARY)
                cost_tracker.record(
                    task="change_summary",
                    model=model_name,
                    usage=result.usage(),
                )
                return result.output.summary

            try:
                loop = asyncio.get_running_loop()
            except RuntimeError:
                loop = None

            if loop and loop.is_running():
                import concurrent.futures

                with concurrent.futures.ThreadPoolExecutor(max_workers=1) as pool:
                    return pool.submit(asyncio.run, _run()).result()
            else:
                return asyncio.run(_run())

        except Exception as e:
            logger.warning(f"Failed to generate AI summary: {e}")
            return report.summary
