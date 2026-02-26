"""Pipeline orchestration helpers for the scrape-parse-normalize-diff workflow.

Contains the core business logic used by Celery tasks. All functions here are
synchronous and operate on a SQLAlchemy sync Session, with asyncio.run() used
only where async I/O is unavoidable (e.g., the document collector).
"""

import asyncio
import json
import logging
from datetime import datetime

from sqlalchemy import select
from sqlalchemy.orm import Session

from exnot.db.models import (
    ChangeType,
    Exchange,
    FeeChange,
    FeeScheduleFormat,
    FeeScheduleSnapshot,
    NormalizedFee,
    ScrapeLog,
    ScrapeStatus,
    SnapshotStatus,
)
from exnot.differ.detector import ChangeDetector, ChangeReport
from exnot.normalizer.schema import NormalizedFeeSchedule
from exnot.parser.ai_extractor import AIExtractor
from exnot.parser.base import ExtractedDocument
from exnot.parser.html_parser import HtmlParser
from exnot.parser.pdf_parser import PdfParser
from exnot.scraper.base import DocumentResult
from exnot.scraper.document import DocumentCollector

logger = logging.getLogger(__name__)


def run_scrape_pipeline(exchange_code: str, session: Session) -> ChangeReport | None:
    """Execute the full scrape-parse-normalize-diff pipeline for a single exchange.

    Args:
        exchange_code: The exchange code to process (e.g., "CBOE", "ARCA").
        session: A synchronous SQLAlchemy session.

    Returns:
        A ChangeReport if changes were detected, or None if the document was
        unchanged or an error occurred.
    """
    # --- Step (a): Load exchange from DB ---
    exchange = session.execute(
        select(Exchange).where(Exchange.code == exchange_code)
    ).scalar_one_or_none()

    if exchange is None:
        logger.error(f"[{exchange_code}] Exchange not found in database")
        return None

    if not exchange.is_active:
        logger.info(f"[{exchange_code}] Exchange is inactive, skipping")
        return None

    # --- Step (b): Collect document (async scraper, bridged via asyncio.run) ---
    logger.info(f"[{exchange_code}] Starting document collection from {exchange.fee_schedule_url}")
    doc_result = _collect_document(exchange)

    # --- Step (c): Compare hash with latest snapshot ---
    latest_snapshot = _get_latest_snapshot(exchange, session)
    latest_hash = latest_snapshot.source_hash if latest_snapshot else None

    if latest_hash == doc_result.content_hash:
        logger.info(f"[{exchange_code}] Document unchanged (hash: {doc_result.content_hash[:12]}...)")
        _record_scrape_log(exchange, session, ScrapeStatus.NO_CHANGE, doc_result.content_hash)
        return None

    logger.info(
        f"[{exchange_code}] Document changed! "
        f"Old hash: {latest_hash[:12] + '...' if latest_hash else 'N/A'}, "
        f"New hash: {doc_result.content_hash[:12]}..."
    )

    # --- Step (d): Create new FeeScheduleSnapshot ---
    new_version = (latest_snapshot.version + 1) if latest_snapshot else 1
    snapshot = FeeScheduleSnapshot(
        exchange_id=exchange.id,
        version=new_version,
        source_url=doc_result.source_url,
        source_hash=doc_result.content_hash,
        raw_document=doc_result.content_bytes,
        status=SnapshotStatus.PENDING,
    )
    session.add(snapshot)
    session.flush()
    logger.info(f"[{exchange_code}] Created snapshot v{new_version} (id: {snapshot.id})")

    # --- Step (e): Parse document ---
    extracted = _parse_document(exchange, doc_result)
    snapshot.raw_text = extracted.full_text
    snapshot.status = SnapshotStatus.PARSED
    session.flush()

    # --- Step (f): Run AI extraction ---
    ai_extractor = AIExtractor()
    extraction_result = ai_extractor.extract(extracted, exchange_code)
    snapshot.ai_extraction = {
        "structural_analysis": extraction_result.structural_analysis,
        "raw_fees_count": len(extraction_result.raw_fees),
        "confidence": extraction_result.confidence,
        "exchange_name": extraction_result.exchange_name,
        "effective_date": extraction_result.effective_date,
        "extraction_notes": extraction_result.extraction_notes,
        "ai_calls_made": extraction_result.ai_calls_made,
    }
    snapshot.parsing_confidence = extraction_result.confidence
    session.flush()

    # --- Step (g): Normalize fees ---
    from exnot.normalizer.engine import NormalizationEngine

    normalizer = NormalizationEngine()
    normalized_schedule = normalizer.normalize(extraction_result, exchange_code)

    # Set effective date on snapshot if found
    if normalized_schedule.effective_date:
        snapshot.effective_date = normalized_schedule.effective_date

    snapshot.normalized_fees_json = json.loads(normalized_schedule.model_dump_json())
    snapshot.status = SnapshotStatus.NORMALIZED
    session.flush()

    # --- Step (h): Save NormalizedFee records ---
    _save_normalized_fees(exchange, snapshot, normalized_schedule, session)

    # --- Step (i): Run change detection against previous snapshot ---
    old_schedule = None
    old_version = None
    if latest_snapshot:
        old_schedule = _reconstruct_schedule(latest_snapshot, exchange_code)
        old_version = latest_snapshot.version

    detector = ChangeDetector()
    change_report = detector.detect(
        old_schedule=old_schedule,
        new_schedule=normalized_schedule,
        old_version=old_version,
        new_version=new_version,
    )

    # --- Step (j): Save FeeChange records ---
    if change_report.has_changes:
        _save_fee_changes(exchange, latest_snapshot, snapshot, change_report, session)
        snapshot.status = SnapshotStatus.VERIFIED
    else:
        snapshot.status = SnapshotStatus.VERIFIED

    session.flush()

    # Record scrape log
    _record_scrape_log(
        exchange, session, ScrapeStatus.SUCCESS, doc_result.content_hash,
        has_changes=change_report.has_changes,
    )

    logger.info(
        f"[{exchange_code}] Pipeline complete. "
        f"{len(change_report.changes)} changes detected in v{new_version}."
    )

    # --- Step (k): Return the change report ---
    return change_report


def _collect_document(exchange: Exchange) -> DocumentResult:
    """Run the async document collector in a synchronous context."""

    async def _run():
        collector = DocumentCollector()
        try:
            return await collector.collect(exchange)
        finally:
            await collector.close()

    return asyncio.run(_run())


def _get_latest_snapshot(exchange: Exchange, session: Session) -> FeeScheduleSnapshot | None:
    """Retrieve the most recent snapshot for the given exchange."""
    result = session.execute(
        select(FeeScheduleSnapshot)
        .where(FeeScheduleSnapshot.exchange_id == exchange.id)
        .order_by(FeeScheduleSnapshot.version.desc())
        .limit(1)
    )
    return result.scalar_one_or_none()


def _parse_document(exchange: Exchange, doc_result: DocumentResult) -> ExtractedDocument:
    """Choose the right parser based on content type and run extraction."""
    if doc_result.is_pdf or exchange.fee_schedule_format == FeeScheduleFormat.PDF:
        logger.info(f"[{exchange.code}] Parsing as PDF")
        parser = PdfParser()
    else:
        logger.info(f"[{exchange.code}] Parsing as HTML")
        parser = HtmlParser()

    return parser.extract(doc_result.content_bytes)


def _save_normalized_fees(
    exchange: Exchange,
    snapshot: FeeScheduleSnapshot,
    schedule: NormalizedFeeSchedule,
    session: Session,
) -> list[NormalizedFee]:
    """Persist NormalizedFee ORM records to the database."""
    db_fees = []
    for entry in schedule.fees:
        fee = NormalizedFee(
            snapshot_id=snapshot.id,
            exchange_id=exchange.id,
            participant_type=entry.participant_type.value,
            security_class=entry.security_class.value,
            order_type=entry.order_type.value,
            fee_type=entry.fee_type.value,
            amount_cents=entry.amount_cents,
            is_rebate=entry.is_rebate,
            volume_tier=entry.volume_tier,
            tier_threshold_pct=entry.tier_threshold_pct,
            tier_threshold_contracts=entry.tier_threshold_contracts,
            effective_date=entry.effective_date,
            notes=entry.notes,
        )
        db_fees.append(fee)

    session.add_all(db_fees)
    session.flush()
    logger.info(f"[{exchange.code}] Saved {len(db_fees)} normalized fee records")
    return db_fees


def _reconstruct_schedule(
    snapshot: FeeScheduleSnapshot, exchange_code: str
) -> NormalizedFeeSchedule | None:
    """Reconstruct a NormalizedFeeSchedule from a stored snapshot's JSON."""
    if snapshot.normalized_fees_json is None:
        return None

    try:
        return NormalizedFeeSchedule.model_validate(snapshot.normalized_fees_json)
    except Exception:
        logger.warning(
            f"[{exchange_code}] Failed to reconstruct schedule from snapshot "
            f"v{snapshot.version}, falling back to None"
        )
        return None


def _save_fee_changes(
    exchange: Exchange,
    old_snapshot: FeeScheduleSnapshot | None,
    new_snapshot: FeeScheduleSnapshot,
    report: ChangeReport,
    session: Session,
) -> list[FeeChange]:
    """Persist FeeChange ORM records from the change report."""
    db_changes = []
    for change_entry in report.changes:
        change = FeeChange(
            exchange_id=exchange.id,
            old_snapshot_id=old_snapshot.id if old_snapshot else None,
            new_snapshot_id=new_snapshot.id,
            change_type=ChangeType(change_entry.change_type),
            participant_type=change_entry.participant_type,
            security_class=change_entry.security_class,
            order_type=change_entry.order_type,
            fee_type=change_entry.fee_type,
            old_amount_cents=change_entry.old_amount_cents,
            new_amount_cents=change_entry.new_amount_cents,
            change_description=change_entry.description,
            notified=False,
        )
        db_changes.append(change)

    session.add_all(db_changes)
    session.flush()
    logger.info(f"[{exchange.code}] Saved {len(db_changes)} fee change records")
    return db_changes


def _record_scrape_log(
    exchange: Exchange,
    session: Session,
    status: ScrapeStatus,
    document_hash: str | None = None,
    has_changes: bool = False,
    error_message: str | None = None,
) -> ScrapeLog:
    """Create a ScrapeLog record for the current scrape run."""
    log = ScrapeLog(
        exchange_id=exchange.id,
        status=status,
        document_hash=document_hash,
        has_changes=has_changes,
        error_message=error_message,
        completed_at=datetime.utcnow(),
    )
    session.add(log)
    session.flush()
    return log
