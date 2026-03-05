"""Celery task definitions for ExNot worker infrastructure.

All tasks are synchronous. Async operations (scraping, email sending) are
bridged via asyncio.run(). Database access uses the sync session from
exnot.db.engine.get_sync_session().
"""

import asyncio
import json
import logging
from dataclasses import asdict
from datetime import datetime, timedelta

from sqlalchemy import delete, select

from exnot.db.engine import get_sync_session
from exnot.db.models import (
    DiscoveryStatus,
    Exchange,
    FeeChange,
    NotificationFrequency,
    NotificationLog,
    ScrapeLog,
    ScrapeStatus,
    Subscriber,
)
from exnot.differ.detector import ChangeReport, FeeChangeEntry
from exnot.notifications.email_sender import EmailSender
from exnot.workers.celery_app import celery_app
from exnot.workers.pipelines import run_scrape_pipeline

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Task: daily_fee_schedule_check
# ---------------------------------------------------------------------------


@celery_app.task(name="exnot.workers.tasks.daily_fee_schedule_check")
def daily_fee_schedule_check():
    """Get all active exchanges and dispatch scrape_and_process_exchange for each."""
    logger.info("Starting daily fee schedule check")

    session = get_sync_session()
    try:
        exchanges = session.execute(select(Exchange).where(Exchange.is_active.is_(True))).scalars().all()

        exchange_codes = [ex.code for ex in exchanges]
        logger.info(f"Found {len(exchange_codes)} active exchanges: {exchange_codes}")

        for code in exchange_codes:
            scrape_and_process_exchange.delay(code)

        logger.info(f"Dispatched scrape tasks for {len(exchange_codes)} exchanges")
        return {"exchanges_dispatched": exchange_codes}
    except Exception:
        logger.exception("Error in daily_fee_schedule_check")
        raise
    finally:
        session.close()


# ---------------------------------------------------------------------------
# Task: discover_exchange_urls
# ---------------------------------------------------------------------------


@celery_app.task(
    name="exnot.workers.tasks.discover_exchange_urls",
    bind=True,
    max_retries=2,
    default_retry_delay=120,
    rate_limit="3/m",
)
def discover_exchange_urls(self, exchange_code: str, force: bool = False):
    """Discover fee schedule URLs for a single exchange via web search + AI."""
    logger.info(f"[{exchange_code}] Starting URL discovery task")
    session = get_sync_session()
    try:
        from exnot.discovery.pipeline import run_discovery_pipeline

        success = run_discovery_pipeline(exchange_code, session, force=force)
        session.commit()
        return {"exchange_code": exchange_code, "success": success}
    except Exception as exc:
        session.rollback()
        logger.exception(f"[{exchange_code}] Discovery failed")
        raise self.retry(exc=exc)
    finally:
        session.close()


@celery_app.task(name="exnot.workers.tasks.discover_all_exchange_urls")
def discover_all_exchange_urls(force: bool = False):
    """Discover URLs for all exchanges that need discovery."""
    session = get_sync_session()
    try:
        if force:
            exchanges = session.execute(select(Exchange).where(Exchange.is_active.is_(True))).scalars().all()
        else:
            exchanges = (
                session.execute(
                    select(Exchange).where(
                        Exchange.is_active.is_(True),
                        Exchange.discovery_status.in_(
                            [
                                DiscoveryStatus.NOT_DISCOVERED,
                                DiscoveryStatus.FAILED,
                                DiscoveryStatus.STALE,
                            ]
                        ),
                    )
                )
                .scalars()
                .all()
            )

        codes = [ex.code for ex in exchanges]
        logger.info(f"Dispatching discovery for {len(codes)} exchanges: {codes}")

        for code in codes:
            discover_exchange_urls.delay(code, force=force)

        return {"dispatched": codes}
    finally:
        session.close()


# ---------------------------------------------------------------------------
# Task: scrape_and_process_exchange
# ---------------------------------------------------------------------------


@celery_app.task(
    name="exnot.workers.tasks.scrape_and_process_exchange",
    bind=True,
    max_retries=0,
)
def scrape_and_process_exchange(self, exchange_code: str, force: bool = False):
    """Full scrape-parse-normalize-diff pipeline for a single exchange.

    Delegates the core logic to run_scrape_pipeline() and then triggers
    notifications if changes were detected.
    """
    # Dedup: skip if another worker is already processing this exchange
    import redis

    redis_client = redis.from_url(celery_app.conf.broker_url)
    lock_key = f"exnot:scrape_lock:{exchange_code}"
    lock = redis_client.lock(lock_key, timeout=1800, blocking=False)
    if not lock.acquire(blocking=False):
        logger.info(f"[{exchange_code}] Skipping — another worker is already processing this exchange")
        return {"exchange_code": exchange_code, "skipped": True, "reason": "duplicate"}

    logger.info(f"[{exchange_code}] Starting scrape and process pipeline")

    session = get_sync_session()
    try:
        change_report = run_scrape_pipeline(exchange_code, session, celery_task_id=self.request.id, force=force)
        session.commit()

        if change_report is not None and change_report.has_changes:
            logger.info(f"[{exchange_code}] {len(change_report.changes)} changes detected, triggering notifications")
            # Serialize the change report for the notification task
            report_json = json.dumps(asdict(change_report))
            send_change_notifications.delay(exchange_code, report_json)
        elif change_report is None:
            logger.info(f"[{exchange_code}] No changes (document unchanged or inactive)")
        else:
            logger.info(f"[{exchange_code}] Pipeline complete, no fee changes detected")

        return {
            "exchange_code": exchange_code,
            "has_changes": change_report is not None and change_report.has_changes,
            "change_count": len(change_report.changes) if change_report else 0,
        }

    except Exception as exc:
        session.rollback()
        logger.exception(f"[{exchange_code}] Error in scrape_and_process_exchange")

        # Record failure in scrape log
        try:
            _record_failure_log(exchange_code, session, str(exc))
            session.commit()
        except Exception:
            logger.exception(f"[{exchange_code}] Failed to record error scrape log")

        raise
    finally:
        session.close()
        try:
            lock.release()
        except Exception:
            pass  # Lock may have expired


def _record_failure_log(exchange_code: str, session, error_message: str):
    """Record a failed scrape attempt in the scrape log."""
    exchange = session.execute(select(Exchange).where(Exchange.code == exchange_code)).scalar_one_or_none()

    if exchange is None:
        return

    log = ScrapeLog(
        exchange_id=exchange.id,
        status=ScrapeStatus.FAILED,
        error_message=error_message[:2000],  # Truncate long error messages
        completed_at=datetime.utcnow(),
    )
    session.add(log)
    session.flush()


# ---------------------------------------------------------------------------
# Task: send_change_notifications
# ---------------------------------------------------------------------------


@celery_app.task(
    name="exnot.workers.tasks.send_change_notifications",
    bind=True,
    max_retries=3,
    default_retry_delay=60,
)
def send_change_notifications(self, exchange_code: str, change_report_json: str):
    """Send immediate notifications to subscribers for detected fee changes.

    Filters subscribers by their exchange preferences, sends emails to
    IMMEDIATE subscribers, and marks FeeChange records as notified.
    """
    logger.info(f"[{exchange_code}] Sending change notifications")

    session = get_sync_session()
    try:
        # Deserialize the change report
        report_data = json.loads(change_report_json)
        change_report = ChangeReport(
            exchange_code=report_data["exchange_code"],
            old_version=report_data["old_version"],
            new_version=report_data["new_version"],
            changes=[FeeChangeEntry(**c) for c in report_data["changes"]],
            summary=report_data.get("summary", ""),
        )

        # Get all active subscribers
        subscribers = session.execute(select(Subscriber).where(Subscriber.is_active.is_(True))).scalars().all()

        # Filter by exchange preferences
        matching_subscribers = _filter_subscribers_by_exchange(subscribers, exchange_code)

        # Filter for IMMEDIATE frequency only
        immediate_subscribers = [
            s for s in matching_subscribers if s.notification_frequency == NotificationFrequency.IMMEDIATE
        ]

        logger.info(
            f"[{exchange_code}] {len(immediate_subscribers)} immediate subscribers "
            f"(of {len(matching_subscribers)} matching, {len(subscribers)} total)"
        )

        email_sender = EmailSender()
        sent_count = 0
        failed_count = 0

        for subscriber in immediate_subscribers:
            success = asyncio.run(
                email_sender.send_fee_change_alert(
                    recipient_email=subscriber.email,
                    recipient_name=subscriber.name,
                    report=change_report,
                )
            )

            # Record notification log
            notification_log = NotificationLog(
                subscriber_id=subscriber.id,
                email_subject=f"[ExNot] Fee Schedule Change: {exchange_code}",
                delivery_status="SENT" if success else "FAILED",
            )
            session.add(notification_log)

            if success:
                sent_count += 1
            else:
                failed_count += 1

        # Mark FeeChange records as notified
        unnotified_changes = (
            session.execute(
                select(FeeChange).where(
                    FeeChange.exchange_id
                    == session.execute(select(Exchange.id).where(Exchange.code == exchange_code)).scalar_one(),
                    FeeChange.notified.is_(False),
                )
            )
            .scalars()
            .all()
        )

        for change in unnotified_changes:
            change.notified = True

        session.commit()

        logger.info(f"[{exchange_code}] Notifications sent: {sent_count} succeeded, {failed_count} failed")

        return {
            "exchange_code": exchange_code,
            "sent": sent_count,
            "failed": failed_count,
        }

    except Exception as exc:
        session.rollback()
        logger.exception(f"[{exchange_code}] Error sending change notifications")
        raise self.retry(exc=exc)
    finally:
        session.close()


# ---------------------------------------------------------------------------
# Task: send_daily_digest
# ---------------------------------------------------------------------------


@celery_app.task(
    name="exnot.workers.tasks.send_daily_digest",
    bind=True,
    max_retries=3,
    default_retry_delay=60,
)
def send_daily_digest(self):
    """Send a daily digest email to DAILY_DIGEST subscribers.

    Gathers all unnotified fee changes from the last 24 hours, groups them
    by exchange, and sends a single consolidated email per subscriber.
    """
    logger.info("Starting daily digest")

    session = get_sync_session()
    try:
        cutoff = datetime.utcnow() - timedelta(days=1)

        # Get unnotified changes from the last 24 hours
        changes = (
            session.execute(
                select(FeeChange)
                .where(
                    FeeChange.notified.is_(False),
                    FeeChange.detected_at >= cutoff,
                )
                .order_by(FeeChange.detected_at.asc())
            )
            .scalars()
            .all()
        )

        if not changes:
            logger.info("No unnotified changes in the last 24 hours for daily digest")
            return {"sent": 0, "changes_count": 0}

        # Group changes by exchange
        changes_by_exchange = _group_changes_by_exchange(changes, session)

        # Build ChangeReport objects per exchange
        reports = _build_reports_from_grouped_changes(changes_by_exchange)

        # Get DAILY_DIGEST subscribers
        subscribers = (
            session.execute(
                select(Subscriber).where(
                    Subscriber.is_active.is_(True),
                    Subscriber.notification_frequency == NotificationFrequency.DAILY_DIGEST,
                )
            )
            .scalars()
            .all()
        )

        logger.info(
            f"Daily digest: {len(changes)} changes across "
            f"{len(changes_by_exchange)} exchanges for {len(subscribers)} subscribers"
        )

        email_sender = EmailSender()
        sent_count = 0

        for subscriber in subscribers:
            # Filter reports by subscriber's exchange preferences
            filtered_reports = _filter_reports_for_subscriber(reports, subscriber)
            if not filtered_reports:
                continue

            success = asyncio.run(
                email_sender.send_daily_digest(
                    recipient_email=subscriber.email,
                    recipient_name=subscriber.name,
                    reports=filtered_reports,
                )
            )

            notification_log = NotificationLog(
                subscriber_id=subscriber.id,
                email_subject=f"[ExNot] Daily Fee Schedule Digest - {len(filtered_reports)} exchange(s) changed",
                delivery_status="SENT" if success else "FAILED",
            )
            session.add(notification_log)

            if success:
                sent_count += 1

        # Mark all digest changes as notified
        for change in changes:
            change.notified = True

        session.commit()

        logger.info(f"Daily digest sent to {sent_count} subscribers")
        return {"sent": sent_count, "changes_count": len(changes)}

    except Exception as exc:
        session.rollback()
        logger.exception("Error sending daily digest")
        raise self.retry(exc=exc)
    finally:
        session.close()


# ---------------------------------------------------------------------------
# Task: send_weekly_summary
# ---------------------------------------------------------------------------


@celery_app.task(
    name="exnot.workers.tasks.send_weekly_summary",
    bind=True,
    max_retries=3,
    default_retry_delay=60,
)
def send_weekly_summary(self):
    """Send a weekly summary email to WEEKLY subscribers.

    Gathers all fee changes from the last 7 days, groups them by exchange,
    and sends a single consolidated email per subscriber.
    """
    logger.info("Starting weekly summary")

    session = get_sync_session()
    try:
        cutoff = datetime.utcnow() - timedelta(days=7)

        # Get all changes from the last 7 days (regardless of notified status)
        changes = (
            session.execute(
                select(FeeChange).where(FeeChange.detected_at >= cutoff).order_by(FeeChange.detected_at.asc())
            )
            .scalars()
            .all()
        )

        if not changes:
            logger.info("No changes in the last 7 days for weekly summary")
            return {"sent": 0, "changes_count": 0}

        # Group changes by exchange
        changes_by_exchange = _group_changes_by_exchange(changes, session)

        # Build ChangeReport objects per exchange
        reports = _build_reports_from_grouped_changes(changes_by_exchange)

        # Get WEEKLY subscribers
        subscribers = (
            session.execute(
                select(Subscriber).where(
                    Subscriber.is_active.is_(True),
                    Subscriber.notification_frequency == NotificationFrequency.WEEKLY,
                )
            )
            .scalars()
            .all()
        )

        logger.info(
            f"Weekly summary: {len(changes)} changes across "
            f"{len(changes_by_exchange)} exchanges for {len(subscribers)} subscribers"
        )

        email_sender = EmailSender()
        sent_count = 0

        for subscriber in subscribers:
            filtered_reports = _filter_reports_for_subscriber(reports, subscriber)
            if not filtered_reports:
                continue

            success = asyncio.run(
                email_sender.send_daily_digest(
                    recipient_email=subscriber.email,
                    recipient_name=subscriber.name,
                    reports=filtered_reports,
                )
            )

            notification_log = NotificationLog(
                subscriber_id=subscriber.id,
                email_subject=f"[ExNot] Weekly Fee Schedule Summary - {len(filtered_reports)} exchange(s)",
                delivery_status="SENT" if success else "FAILED",
            )
            session.add(notification_log)

            if success:
                sent_count += 1

        session.commit()

        logger.info(f"Weekly summary sent to {sent_count} subscribers")
        return {"sent": sent_count, "changes_count": len(changes)}

    except Exception as exc:
        session.rollback()
        logger.exception("Error sending weekly summary")
        raise self.retry(exc=exc)
    finally:
        session.close()


# ---------------------------------------------------------------------------
# Task: cleanup_old_scrape_logs
# ---------------------------------------------------------------------------


@celery_app.task(name="exnot.workers.tasks.cleanup_old_scrape_logs")
def cleanup_old_scrape_logs(days: int = 90):
    """Delete ScrapeLog records older than the specified number of days."""
    logger.info(f"Cleaning up scrape logs older than {days} days")

    session = get_sync_session()
    try:
        cutoff = datetime.utcnow() - timedelta(days=days)

        result = session.execute(delete(ScrapeLog).where(ScrapeLog.started_at < cutoff))

        deleted_count = result.rowcount
        session.commit()

        logger.info(f"Deleted {deleted_count} scrape log records older than {days} days")
        return {"deleted": deleted_count, "days_threshold": days}

    except Exception:
        session.rollback()
        logger.exception("Error cleaning up scrape logs")
        raise
    finally:
        session.close()


# ---------------------------------------------------------------------------
# Helper functions
# ---------------------------------------------------------------------------


def _filter_subscribers_by_exchange(subscribers: list[Subscriber], exchange_code: str) -> list[Subscriber]:
    """Filter subscribers to those interested in the given exchange.

    If a subscriber's exchanges_filter is None, they receive all exchanges.
    Otherwise, the exchange_code must be in their filter list.
    """
    matching = []
    for subscriber in subscribers:
        if subscriber.exchanges_filter is None:
            # No filter means all exchanges
            matching.append(subscriber)
        elif isinstance(subscriber.exchanges_filter, list):
            if exchange_code in subscriber.exchanges_filter:
                matching.append(subscriber)
        elif isinstance(subscriber.exchanges_filter, dict):
            # Handle dict-style filter like {"exchanges": ["CBOE", "ARCA"]}
            exchange_list = subscriber.exchanges_filter.get("exchanges", [])
            if not exchange_list or exchange_code in exchange_list:
                matching.append(subscriber)
    return matching


def _group_changes_by_exchange(changes: list[FeeChange], session) -> dict[str, list[FeeChange]]:
    """Group FeeChange records by their exchange code."""
    # Build an exchange_id -> code mapping
    exchange_ids = {c.exchange_id for c in changes}
    exchanges = session.execute(select(Exchange).where(Exchange.id.in_(exchange_ids))).scalars().all()
    id_to_code = {ex.id: ex.code for ex in exchanges}

    grouped: dict[str, list[FeeChange]] = {}
    for change in changes:
        code = id_to_code.get(change.exchange_id, "UNKNOWN")
        grouped.setdefault(code, []).append(change)

    return grouped


def _build_reports_from_grouped_changes(
    changes_by_exchange: dict[str, list[FeeChange]],
) -> list[ChangeReport]:
    """Convert grouped FeeChange DB records into ChangeReport objects for email."""
    reports = []
    for exchange_code, changes in changes_by_exchange.items():
        change_entries = []
        for c in changes:
            change_entries.append(
                FeeChangeEntry(
                    change_type=c.change_type.value if hasattr(c.change_type, "value") else c.change_type,
                    participant_type=c.participant_type.value
                    if hasattr(c.participant_type, "value")
                    else c.participant_type,
                    security_class=c.security_class.value if hasattr(c.security_class, "value") else c.security_class,
                    order_type=c.order_type.value if hasattr(c.order_type, "value") else c.order_type,
                    fee_type=c.fee_type.value if hasattr(c.fee_type, "value") else c.fee_type,
                    old_amount_cents=c.old_amount_cents,
                    new_amount_cents=c.new_amount_cents,
                    description=c.change_description or "",
                )
            )

        report = ChangeReport(
            exchange_code=exchange_code,
            old_version=None,
            new_version=0,
            changes=change_entries,
            summary=f"{len(change_entries)} fee change(s) detected for {exchange_code}.",
        )
        reports.append(report)

    return reports


def _filter_reports_for_subscriber(reports: list[ChangeReport], subscriber: Subscriber) -> list[ChangeReport]:
    """Filter change reports based on subscriber's exchange preferences."""
    if subscriber.exchanges_filter is None:
        return reports

    if isinstance(subscriber.exchanges_filter, list):
        allowed = set(subscriber.exchanges_filter)
    elif isinstance(subscriber.exchanges_filter, dict):
        allowed = set(subscriber.exchanges_filter.get("exchanges", []))
        if not allowed:
            return reports
    else:
        return reports

    return [r for r in reports if r.exchange_code in allowed]
