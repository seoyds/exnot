"""Generate human-readable change reports, optionally AI-enhanced."""

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
                    lines.append(f"  {c.participant_type} | {c.security_class} | {c.fee_type}: {old} → {new}")
            lines.append("")

        if report.new_count:
            lines.append("=== NEW FEES ===")
            for c in report.changes:
                if c.change_type == "NEW":
                    amt = f"${c.new_amount_cents / 10000:.4f}" if c.new_amount_cents is not None else "N/A"
                    lines.append(f"  {c.participant_type} | {c.security_class} | {c.fee_type}: {amt}")
            lines.append("")

        if report.removed_count:
            lines.append("=== REMOVED FEES ===")
            for c in report.changes:
                if c.change_type == "REMOVED":
                    amt = f"${c.old_amount_cents / 10000:.4f}" if c.old_amount_cents is not None else "N/A"
                    lines.append(f"  {c.participant_type} | {c.security_class} | {c.fee_type}: {amt}")

        return "\n".join(lines)

    def generate_ai_summary(self, report: ChangeReport) -> str:
        """Generate a human-readable summary of changes.

        TODO: Re-implement via Agent SDK summarizer subagent.
        Currently returns the basic report summary.
        """
        if not report.has_changes:
            return report.summary

        parts = [report.summary]
        if report.modified_count:
            parts.append(f"{report.modified_count} fee(s) modified")
        if report.new_count:
            parts.append(f"{report.new_count} new fee(s) added")
        if report.removed_count:
            parts.append(f"{report.removed_count} fee(s) removed")
        return ". ".join(parts) + "."
