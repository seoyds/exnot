"""Notification tool — email subscribers about fee changes."""

import json
import logging

from claude_agent_sdk import tool

logger = logging.getLogger(__name__)


@tool(
    "send_notifications",
    "Send fee change notification emails to all active subscribers. "
    "Takes the exchange code, changes as JSON, and an AI-generated summary.",
    {"exchange_code": str, "changes_json": str, "summary": str},
)
async def send_notifications(args):
    try:
        from exnot.db.engine import AsyncSessionLocal
        from exnot.db.repositories import SubscriberRepository
        from exnot.differ.detector import ChangeReport, FeeChangeEntry
        from exnot.notifications.email_sender import EmailSender

        exchange_code = args["exchange_code"]
        changes = json.loads(args["changes_json"])
        summary = args.get("summary", "")

        if not changes:
            return {
                "content": [
                    {
                        "type": "text",
                        "text": json.dumps(
                            {
                                "sent": 0,
                                "reason": "No changes to notify about",
                            }
                        ),
                    }
                ]
            }

        # Build ChangeReport for the email template
        change_entries = []
        for c in changes:
            change_entries.append(
                FeeChangeEntry(
                    change_type=c["change_type"],
                    participant_type=c.get("participant_type"),
                    security_class=c.get("security_class"),
                    order_type=c.get("order_type"),
                    fee_type=c.get("fee_type"),
                    old_amount_cents=c.get("old_amount_cents"),
                    new_amount_cents=c.get("new_amount_cents"),
                    volume_tier=c.get("volume_tier"),
                    description=c.get("description", ""),
                )
            )

        report = ChangeReport(
            exchange_code=exchange_code,
            old_version=None,
            new_version=1,
            changes=change_entries,
            summary=summary,
        )

        # Get active subscribers
        async with AsyncSessionLocal() as session:
            subscriber_repo = SubscriberRepository(session)
            subscribers = await subscriber_repo.get_all_active()

        if not subscribers:
            return {
                "content": [
                    {
                        "type": "text",
                        "text": json.dumps(
                            {"sent": 0, "reason": "No active subscribers"}
                        ),
                    }
                ]
            }

        # Send emails
        sender = EmailSender()
        sent_count = 0
        failed_count = 0

        for subscriber in subscribers:
            try:
                success = await sender.send_fee_change_alert(
                    recipient_email=subscriber.email,
                    recipient_name=subscriber.name,
                    report=report,
                    ai_summary=summary,
                )
                if success:
                    sent_count += 1
                else:
                    failed_count += 1
            except Exception as e:
                logger.warning(
                    f"Failed to send notification to {subscriber.email}: {e}"
                )
                failed_count += 1

        return {
            "content": [
                {
                    "type": "text",
                    "text": json.dumps(
                        {
                            "sent": sent_count,
                            "failed": failed_count,
                            "total_subscribers": len(subscribers),
                            "exchange_code": exchange_code,
                            "change_count": len(changes),
                        }
                    ),
                }
            ]
        }
    except Exception as e:
        logger.error(f"send_notifications failed: {e}")
        return {
            "content": [
                {"type": "text", "text": json.dumps({"error": str(e)})}
            ]
        }
