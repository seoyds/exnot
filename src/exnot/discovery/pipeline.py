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
from exnot.discovery.discoverer import UrlDiscoverer

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

    result = asyncio.run(
        _run_async_discovery(exchange.code, exchange.name, exchange.operator)
    )

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

    if result.primary_url and result.confidence >= 0.5:
        exchange.fee_schedule_url = result.primary_url
        exchange.alternate_urls = result.alternate_urls if result.alternate_urls else []
        exchange.fee_schedule_format = FORMAT_MAP.get(
            result.recommended_format, exchange.fee_schedule_format
        )
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


async def _run_async_discovery(exchange_code: str, exchange_name: str, operator: str):
    discoverer = UrlDiscoverer()
    return await discoverer.discover(
        exchange_code=exchange_code,
        exchange_name=exchange_name,
        operator=operator,
    )
