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
    DiscoveryStatus,
    Exchange,
    ExchangeProfile,
    FeeChange,
    FeeScheduleFormat,
    FeeScheduleSnapshot,
    FeeTier,
    NormalizedFee,
    ProfileStatus,
    ScrapedDocument,
    ScrapeLog,
    ScrapeStatus,
    SnapshotStatus,
)
from exnot.differ.detector import ChangeDetector, ChangeReport
from exnot.normalizer.schema import NormalizedFeeSchedule
from exnot.parser.ai_extractor import AIExtractor
from exnot.parser.base import ExtractedDocument
from exnot.parser.csv_parser import CsvParser
from exnot.parser.html_parser import HtmlParser
from exnot.parser.factory import get_pdf_parser
from exnot.scraper.base import CollectionResult, DocumentResult
from exnot.scraper.document import DocumentCollector
from exnot.storage.minio_client import DocumentStorage

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

    # --- Step (a2): Run URL discovery if needed ---
    if exchange.discovery_status != DiscoveryStatus.DISCOVERED:
        logger.info(f"[{exchange_code}] URLs not yet discovered, running discovery first...")
        from exnot.discovery.pipeline import run_discovery_pipeline

        success = run_discovery_pipeline(exchange_code, session)
        session.flush()
        if not success:
            logger.error(f"[{exchange_code}] Discovery failed, cannot proceed with scrape")
            _record_scrape_log(exchange, session, ScrapeStatus.FAILED, error_message="URL discovery failed")
            return None
        session.refresh(exchange)

    # --- Step (b): Collect documents (async scraper, bridged via asyncio.run) ---
    logger.info(f"[{exchange_code}] Starting document collection from {exchange.fee_schedule_url}")
    collection = _collect_documents(exchange)

    # --- Step (c): Compare hash with latest snapshot (uses primary doc hash) ---
    latest_snapshot = _get_latest_snapshot(exchange, session)
    latest_hash = latest_snapshot.source_hash if latest_snapshot else None

    if latest_hash == collection.primary_hash:
        logger.info(f"[{exchange_code}] Document unchanged (hash: {collection.primary_hash[:12]}...)")
        _record_scrape_log(exchange, session, ScrapeStatus.NO_CHANGE, collection.primary_hash)
        return None

    logger.info(
        f"[{exchange_code}] Document changed! "
        f"Old hash: {latest_hash[:12] + '...' if latest_hash else 'N/A'}, "
        f"New hash: {collection.primary_hash[:12]}..."
    )

    # --- Step (d): Create new FeeScheduleSnapshot ---
    new_version = (latest_snapshot.version + 1) if latest_snapshot else 1
    snapshot = FeeScheduleSnapshot(
        exchange_id=exchange.id,
        version=new_version,
        source_url=collection.primary.source_url,
        source_hash=collection.primary_hash,
        raw_document=None,  # Documents now stored in MinIO
        status=SnapshotStatus.PENDING,
    )
    session.add(snapshot)
    session.flush()
    logger.info(f"[{exchange_code}] Created snapshot v{new_version} (id: {snapshot.id})")

    # --- Step (d2): Store all documents in MinIO + create ScrapedDocument records ---
    _store_documents(exchange, snapshot, collection, session)

    # --- Step (e): Parse primary document + supplementary docs for full context ---
    extracted = _parse_document(exchange, collection.primary)

    # When primary is CSV, also parse the HTML version for tier details and footnotes
    if collection.primary.is_csv:
        supplementary = _parse_supplementary_html(exchange, collection)
        if supplementary:
            extracted = _merge_extracted_documents(extracted, supplementary)
            logger.info(f"[{exchange_code}] Merged HTML supplement ({len(supplementary.tables)} tables, "
                        f"{len(supplementary.full_text)} chars) with CSV primary")

    snapshot.raw_text = extracted.full_text
    snapshot.status = SnapshotStatus.PARSED
    session.flush()

    # --- Step (f): Try profile-based extraction, fall back to AI ---
    profile_fees = _try_profile_extraction(exchange, extracted, session)

    if profile_fees is not None:
        # Rules-based extraction succeeded — skip AI
        logger.info(f"[{exchange_code}] Using profile-based extraction ({len(profile_fees)} fees)")
        snapshot.ai_extraction = {
            "extraction_mode": "PROFILE",
            "raw_fees_count": len(profile_fees),
            "ai_calls_made": 0,
        }
        snapshot.parsing_confidence = 1.0
        session.flush()

        from exnot.normalizer.engine import NormalizationEngine
        from exnot.parser.ai_extractor import ExtractionResult

        # Wrap profile fees in ExtractionResult for normalizer compatibility
        extraction_result = ExtractionResult(
            raw_fees=profile_fees,
            confidence=1.0,
            exchange_name=exchange.name,
            extraction_notes="Profile-based extraction (zero AI)",
        )
        normalizer = NormalizationEngine()
        normalized_schedule = normalizer.normalize(extraction_result, exchange_code)
    else:
        # AI extraction (existing path)
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

        from exnot.normalizer.engine import NormalizationEngine

        normalizer = NormalizationEngine()
        normalized_schedule = normalizer.normalize(extraction_result, exchange_code)

        # Build/update profile from AI results
        _build_and_save_profile(exchange, extracted, extraction_result.raw_fees, session)

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
    session.flush()

    # Record scrape log
    _record_scrape_log(
        exchange, session, ScrapeStatus.SUCCESS, collection.primary_hash,
        has_changes=change_report.has_changes,
    )

    logger.info(
        f"[{exchange_code}] Pipeline complete. "
        f"{len(change_report.changes)} changes detected in v{new_version}."
    )

    # --- Step (k): Return the change report ---
    return change_report


def _try_profile_extraction(
    exchange: Exchange,
    document: ExtractedDocument,
    session: Session,
) -> list[dict] | None:
    """Attempt rules-based extraction using stored profile.

    Returns list of fee dicts if profile extraction succeeds, None if AI needed.
    """
    from exnot.profiles.extractor import extract_all_from_profile
    from exnot.profiles.fingerprint import compare_fingerprints, fingerprint_all_tables

    profile = session.execute(
        select(ExchangeProfile).where(ExchangeProfile.exchange_id == exchange.id)
    ).scalar_one_or_none()

    if not profile or profile.status != ProfileStatus.ACTIVE:
        logger.info(f"[{exchange.code}] No active profile, will use AI extraction")
        return None

    # Compare fingerprints
    current_fps = fingerprint_all_tables(document.tables)
    comparison = compare_fingerprints(profile.table_fingerprints, current_fps)

    if not comparison.all_match:
        changed_pct = comparison.changed_ratio
        if changed_pct > 0.5:
            logger.info(
                f"[{exchange.code}] Major table structure change ({changed_pct:.0%}), "
                f"rebuilding profile with AI"
            )
        else:
            logger.info(
                f"[{exchange.code}] Minor table changes detected "
                f"({len(comparison.changed_indices)} tables changed), "
                f"falling back to AI for this run"
            )
        profile.status = ProfileStatus.NEEDS_UPDATE
        session.flush()
        return None

    # All fingerprints match — rules-based extraction
    logger.info(f"[{exchange.code}] All table fingerprints match profile, using rules-based extraction")
    fees = extract_all_from_profile(document.tables, profile.table_mappings)
    expected = profile.extraction_stats.get("expected_fee_count", "?")
    logger.info(f"[{exchange.code}] Profile extraction: {len(fees)} fees (expected {expected})")

    return fees


def _build_and_save_profile(
    exchange: Exchange,
    document: ExtractedDocument,
    ai_fees: list[dict],
    session: Session,
) -> None:
    """Build a profile from AI extraction and save it."""
    from exnot.profiles.builder import ProfileBuilder

    builder = ProfileBuilder()
    result = builder.build(document.tables, ai_fees)

    # Only save as ACTIVE if match ratio is good
    status = ProfileStatus.ACTIVE if result.match_ratio >= 0.7 else ProfileStatus.LEARNING

    # Check if profile already exists
    profile = session.execute(
        select(ExchangeProfile).where(ExchangeProfile.exchange_id == exchange.id)
    ).scalar_one_or_none()

    if profile:
        profile.table_mappings = result.table_mappings
        profile.table_fingerprints = result.table_fingerprints
        profile.extraction_stats = result.extraction_stats
        profile.status = status
        profile.profile_version += 1
    else:
        profile = ExchangeProfile(
            exchange_id=exchange.id,
            profile_version=1,
            table_mappings=result.table_mappings,
            table_fingerprints=result.table_fingerprints,
            section_metadata={},
            extraction_stats=result.extraction_stats,
            status=status,
        )
        session.add(profile)

    session.flush()
    logger.info(
        f"[{exchange.code}] Profile {'updated' if profile.profile_version > 1 else 'created'}: "
        f"status={status.value}, match_ratio={result.match_ratio:.0%}, "
        f"v{profile.profile_version}"
    )


def _collect_documents(exchange: Exchange) -> CollectionResult:
    """Run the async document collector in a synchronous context."""

    async def _run():
        collector = DocumentCollector()
        try:
            return await collector.collect(exchange)
        finally:
            await collector.close()

    return asyncio.run(_run())


def _store_documents(
    exchange: Exchange,
    snapshot: FeeScheduleSnapshot,
    collection: CollectionResult,
    session: Session,
) -> None:
    """Upload all collected documents to MinIO and create ScrapedDocument records."""
    storage = DocumentStorage()

    for doc in collection.documents:
        filename = f"fee_schedule{doc.filename_extension}"
        # Avoid name collisions when multiple docs share the same extension
        existing_paths = [
            d.storage_path for d in session.query(ScrapedDocument).filter_by(snapshot_id=snapshot.id).all()
        ]
        object_name = DocumentStorage.build_object_name(exchange.code, snapshot.version, filename)
        counter = 1
        while object_name in existing_paths:
            base = f"fee_schedule_{counter}{doc.filename_extension}"
            object_name = DocumentStorage.build_object_name(exchange.code, snapshot.version, base)
            counter += 1

        stored = storage.store(object_name, doc.content_bytes, content_type=doc.content_type.value)

        record = ScrapedDocument(
            snapshot_id=snapshot.id,
            content_type=doc.content_type.value,
            source_url=doc.source_url,
            content_hash=doc.content_hash,
            storage_path=stored.object_name,
            file_size_bytes=stored.size_bytes,
            is_primary=(doc.content_hash == collection.primary.content_hash),
            fetched_at=doc.fetched_at,
        )
        session.add(record)

    session.flush()
    logger.info(f"[{exchange.code}] Stored {len(collection.documents)} document(s) in MinIO")


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
    if doc_result.is_csv or exchange.fee_schedule_format == FeeScheduleFormat.CSV:
        logger.info(f"[{exchange.code}] Parsing as CSV")
        parser = CsvParser()
    elif doc_result.is_pdf or exchange.fee_schedule_format == FeeScheduleFormat.PDF:
        logger.info(f"[{exchange.code}] Parsing as PDF")
        parser = get_pdf_parser()
    else:
        logger.info(f"[{exchange.code}] Parsing as HTML")
        parser = HtmlParser()

    return parser.extract(doc_result.content_bytes)


def _parse_supplementary_html(
    exchange: Exchange, collection: CollectionResult
) -> ExtractedDocument | None:
    """Find and parse an HTML document from the collection to supplement CSV data."""
    from exnot.scraper.base import ContentType

    for doc in collection.documents:
        if doc.content_type == ContentType.HTML and doc.content_hash != collection.primary.content_hash:
            logger.info(f"[{exchange.code}] Parsing supplementary HTML from {doc.source_url}")
            parser = HtmlParser()
            return parser.extract(doc.content_bytes)

    logger.info(f"[{exchange.code}] No supplementary HTML document found in collection")
    return None


def _merge_extracted_documents(
    primary: ExtractedDocument, supplementary: ExtractedDocument
) -> ExtractedDocument:
    """Merge a supplementary document into the primary, combining text and tables."""
    merged_text = (
        primary.full_text
        + "\n\n--- SUPPLEMENTARY HTML PAGE (use this for tier conditions, footnotes, "
        "and contra-party details to ENRICH the fees above — do NOT create separate "
        "fee entries from this section alone; instead attach tier_group, tier_number, "
        "tier_conditions, contra_party_type, and conditions to the matching CSV fees) ---\n\n"
        + supplementary.full_text
    )
    merged_tables = primary.tables + supplementary.tables
    merged_metadata = {**primary.metadata, "supplementary_tables": len(supplementary.tables)}

    return ExtractedDocument(
        full_text=merged_text,
        tables=merged_tables,
        page_count=primary.page_count,
        metadata=merged_metadata,
    )


def _save_fee_tiers(
    exchange: Exchange,
    snapshot: FeeScheduleSnapshot,
    schedule: NormalizedFeeSchedule,
    session: Session,
) -> dict[str, dict[int, FeeTier]]:
    """Create FeeTier records from tier groups found in the schedule.

    Returns a nested dict: tier_group -> tier_number -> FeeTier ORM object.
    """
    tier_map: dict[str, dict[int, FeeTier]] = {}

    for entry in schedule.fees:
        if not entry.tier_group or entry.tier_number is None:
            continue
        group = entry.tier_group
        num = entry.tier_number
        if group not in tier_map:
            tier_map[group] = {}
        if num in tier_map[group]:
            continue  # Already created this tier

        conditions = {}
        if entry.tier_conditions:
            conditions = entry.tier_conditions.model_dump()

        tier = FeeTier(
            snapshot_id=snapshot.id,
            exchange_id=exchange.id,
            tier_group=group,
            tier_number=num,
            tier_name=f"{group} Tier {num}",
            conditions=conditions,
            is_retroactive=True,
            notes=entry.notes,
        )
        session.add(tier)
        tier_map[group][num] = tier

    if tier_map:
        session.flush()
        total = sum(len(tiers) for tiers in tier_map.values())
        logger.info(f"[{exchange.code}] Saved {total} fee tier records")

    return tier_map


def _save_normalized_fees(
    exchange: Exchange,
    snapshot: FeeScheduleSnapshot,
    schedule: NormalizedFeeSchedule,
    session: Session,
) -> list[NormalizedFee]:
    """Persist NormalizedFee ORM records to the database."""
    # First, create FeeTier records and build a lookup
    tier_map = _save_fee_tiers(exchange, snapshot, schedule, session)

    db_fees = []
    for entry in schedule.fees:
        # Resolve tier_id from the tier_map
        tier_id = None
        if entry.tier_group and entry.tier_number is not None:
            tier_obj = tier_map.get(entry.tier_group, {}).get(entry.tier_number)
            if tier_obj:
                tier_id = tier_obj.id

        # Serialize conditions to JSONB
        conditions = None
        if entry.conditions:
            conditions = entry.conditions

        fee = NormalizedFee(
            snapshot_id=snapshot.id,
            exchange_id=exchange.id,
            participant_type=entry.participant_type.value,
            security_class=entry.security_class.value,
            order_type=entry.order_type.value,
            fee_type=entry.fee_type.value,
            amount_cents=entry.amount_cents,
            is_rebate=entry.is_rebate,
            fee_code=entry.fee_code,
            contra_party_type=entry.contra_party_type.value if entry.contra_party_type else None,
            symbol=entry.symbol,
            fee_unit=entry.fee_unit.value if entry.fee_unit else "PER_CONTRACT",
            tier_id=tier_id,
            routing_destination=entry.routing_destination,
            conditions=conditions,
            effective_date=entry.effective_date,
            expiry_date=entry.expiry_date,
            section_ref=entry.section_ref,
            notes=entry.notes,
            # Legacy fields
            volume_tier=entry.volume_tier,
            tier_threshold_pct=entry.tier_threshold_pct,
            tier_threshold_contracts=entry.tier_threshold_contracts,
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
