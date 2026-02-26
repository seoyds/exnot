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
        """Generate an AI-enhanced natural language summary using Claude."""
        if not report.has_changes:
            return report.summary

        try:
            import anthropic

            from exnot.config import get_settings

            settings = get_settings()
            client = anthropic.Anthropic(api_key=settings.anthropic_api_key)

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
                    for c in report.changes[:50]  # Limit to 50 changes
                ],
                indent=2,
            )

            response = client.messages.create(
                model=settings.ai_model,
                max_tokens=1024,
                messages=[
                    {
                        "role": "user",
                        "content": (
                            f"Summarize these fee schedule changes for {report.exchange_code} "
                            f"in 2-3 concise sentences for financial professionals. "
                            f"Focus on the most impactful changes (largest $ changes, "
                            f"changes affecting Customer/Market Maker fees). "
                            f"Mention if the exchange is becoming more or less competitive.\n\n"
                            f"Changes:\n{changes_json}"
                        ),
                    }
                ],
            )
            return response.content[0].text
        except Exception as e:
            logger.warning(f"Failed to generate AI summary: {e}")
            return report.summary
