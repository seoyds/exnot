"""Email notification sender using Gmail SMTP."""

import logging
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText
from pathlib import Path

import aiosmtplib
from jinja2 import Environment, FileSystemLoader

from exnot.config import get_settings
from exnot.differ.detector import ChangeReport

logger = logging.getLogger(__name__)

TEMPLATES_DIR = Path(__file__).parent / "templates"

_jinja_env = Environment(loader=FileSystemLoader(str(TEMPLATES_DIR)), autoescape=True)


class EmailSender:
    """Sends fee change notification emails via Gmail SMTP."""

    def __init__(self):
        settings = get_settings()
        self.host = settings.smtp_host
        self.port = settings.smtp_port
        self.username = settings.smtp_username
        self.password = settings.smtp_password
        self.from_email = settings.email_from
        self.from_name = settings.email_from_name
        self.app_url = settings.app_url

    async def send_fee_change_alert(
        self,
        recipient_email: str,
        recipient_name: str | None,
        report: ChangeReport,
        ai_summary: str = "",
    ) -> bool:
        """Send a fee change alert email."""
        subject = f"[ExNot] Fee Schedule Change: {report.exchange_code}"

        template = _jinja_env.get_template("fee_change.html")
        html_body = template.render(
            recipient_name=recipient_name or "Subscriber",
            exchange_code=report.exchange_code,
            summary=ai_summary or report.summary,
            changes=report.changes,
            new_count=report.new_count,
            modified_count=report.modified_count,
            removed_count=report.removed_count,
            app_url=self.app_url,
            old_version=report.old_version,
            new_version=report.new_version,
        )

        return await self._send(recipient_email, subject, html_body)

    async def send_daily_digest(
        self,
        recipient_email: str,
        recipient_name: str | None,
        reports: list[ChangeReport],
    ) -> bool:
        """Send a daily digest email with all fee changes from the past day."""
        if not reports:
            return True

        subject = f"[ExNot] Daily Fee Schedule Digest - {len(reports)} exchange(s) changed"

        template = _jinja_env.get_template("daily_digest.html")
        html_body = template.render(
            recipient_name=recipient_name or "Subscriber",
            reports=reports,
            total_changes=sum(len(r.changes) for r in reports),
            app_url=self.app_url,
        )

        return await self._send(recipient_email, subject, html_body)

    async def _send(self, to_email: str, subject: str, html_body: str) -> bool:
        """Send an HTML email via SMTP."""
        msg = MIMEMultipart("alternative")
        msg["From"] = f"{self.from_name} <{self.from_email}>"
        msg["To"] = to_email
        msg["Subject"] = subject

        # Plain text fallback
        plain_text = "This email requires an HTML-capable email client. "
        plain_text += "Please view this in your email app or visit the ExNot dashboard."
        msg.attach(MIMEText(plain_text, "plain"))
        msg.attach(MIMEText(html_body, "html"))

        try:
            await aiosmtplib.send(
                msg,
                hostname=self.host,
                port=self.port,
                username=self.username,
                password=self.password,
                start_tls=True,
            )
            logger.info(f"Email sent to {to_email}: {subject}")
            return True
        except Exception as e:
            logger.error(f"Failed to send email to {to_email}: {e}")
            return False
