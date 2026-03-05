"""Discovery pipeline — runs URL discovery and updates Exchange DB records."""

import asyncio
import logging
from datetime import datetime

from sqlalchemy import select
from sqlalchemy.orm import Session

from exnot.db.models import (
    DiscoveryLog,
    DiscoveryStatus,
    Exchange,
    FeeScheduleFormat,
)
from exnot.discovery.discoverer import ClassifiedCandidate, UrlDiscoverer

logger = logging.getLogger(__name__)

FORMAT_MAP = {
    "PDF": FeeScheduleFormat.PDF,
    "CSV": FeeScheduleFormat.CSV,
    "HTML": FeeScheduleFormat.HTML,
    "EXCEL": FeeScheduleFormat.EXCEL,
}


def run_discovery_pipeline(exchange_code: str, session: Session, force: bool = False) -> bool:
    """Run URL discovery for a single exchange.

    Returns True if discovery succeeded and URLs were updated.
    """
    exchange = session.execute(select(Exchange).where(Exchange.code == exchange_code)).scalar_one_or_none()

    if exchange is None:
        logger.error(f"[{exchange_code}] Exchange not found")
        return False

    # Skip if already discovered (unless forced)
    if exchange.discovery_status == DiscoveryStatus.DISCOVERED and not force:
        logger.info(f"[{exchange_code}] Already discovered, skipping (use force=True to re-discover)")
        return True

    logger.info(f"[{exchange_code}] Starting URL discovery...")

    result = asyncio.run(_run_async_discovery(exchange.code, exchange.name, exchange.operator))

    # Record discovery log
    log = DiscoveryLog(
        exchange_id=exchange.id,
        search_queries={"queries": result.search_queries},
        candidate_urls={"candidates": result.all_candidates},
        selected_url=result.primary_url,
        selected_alternates=result.alternate_urls,
        ai_reasoning=result.ai_reasoning,
        status=DiscoveryStatus.DISCOVERED if result.primary_url else DiscoveryStatus.FAILED,
        error_message=result.error,
    )
    session.add(log)

    # Create/update ExchangeDocument records from classified candidates
    if result.classified_candidates:
        try:
            docs = _create_exchange_documents(exchange, result.classified_candidates, session)
            logger.info(f"[{exchange_code}] Created/updated {len(docs)} ExchangeDocument records")
        except Exception as e:
            logger.warning(f"[{exchange_code}] Failed to create ExchangeDocument records: {e}")

    if result.primary_url and result.confidence >= 0.5:
        exchange.fee_schedule_url = result.primary_url
        exchange.alternate_urls = result.alternate_urls if result.alternate_urls else []
        exchange.fee_schedule_format = FORMAT_MAP.get(result.recommended_format, exchange.fee_schedule_format)
        exchange.discovery_status = DiscoveryStatus.DISCOVERED
        exchange.discovered_at = datetime.utcnow()
        exchange.discovery_metadata = {
            "confidence": result.confidence,
            "ai_reasoning": result.ai_reasoning,
            "search_queries": result.search_queries,
            "candidate_count": len(result.all_candidates),
        }
        session.flush()
        logger.info(
            f"[{exchange_code}] Discovery SUCCESS: {result.primary_url} "
            f"(confidence={result.confidence:.2f}, format={result.recommended_format})"
        )
        return True
    else:
        exchange.discovery_status = DiscoveryStatus.FAILED
        exchange.discovery_metadata = {
            "error": result.error or "Low confidence or no URL found",
            "confidence": result.confidence,
        }
        session.flush()
        logger.warning(f"[{exchange_code}] Discovery FAILED: {result.error or 'low confidence'}")
        return False


def _create_exchange_documents(exchange, classified_candidates: list[ClassifiedCandidate], session: Session):
    """Create or update ExchangeDocument records from classified candidates."""
    from exnot.config import get_settings
    from exnot.db.models import DocumentCategory, DocumentStatus, ExchangeDocument

    settings = get_settings()
    threshold = settings.doc_auto_approve_threshold
    created_docs = []

    for candidate in classified_candidates:
        existing = (
            session.query(ExchangeDocument)
            .filter_by(
                exchange_id=exchange.id,
                source_url=candidate.url,
            )
            .first()
        )

        if existing:
            existing.last_seen_at = datetime.utcnow()
            existing.classification_confidence = candidate.classification_confidence
            existing.classification_reasoning = candidate.classification_reasoning
            if existing.status == DocumentStatus.DISCOVERED:
                existing.status = DocumentStatus.CLASSIFIED
                existing.doc_category = DocumentCategory[candidate.doc_category]
            created_docs.append(existing)
            continue

        doc_category = DocumentCategory[candidate.doc_category]
        status = DocumentStatus.CLASSIFIED

        # Auto-approve high-confidence fee schedule docs
        if doc_category == DocumentCategory.FEE_SCHEDULE and candidate.classification_confidence >= threshold:
            status = DocumentStatus.APPROVED

        doc = ExchangeDocument(
            exchange_id=exchange.id,
            source_url=candidate.url,
            title=candidate.title,
            content_type=candidate.content_type,
            doc_category=doc_category,
            status=status,
            classification_confidence=candidate.classification_confidence,
            classification_reasoning=candidate.classification_reasoning,
        )
        session.add(doc)
        created_docs.append(doc)

    session.flush()
    return created_docs


async def _run_async_discovery(exchange_code: str, exchange_name: str, operator: str):
    discoverer = UrlDiscoverer()
    return await discoverer.discover(
        exchange_code=exchange_code,
        exchange_name=exchange_name,
        operator=operator,
    )
