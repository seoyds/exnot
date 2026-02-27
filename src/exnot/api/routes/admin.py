"""Admin API endpoints for manual operations."""

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.ext.asyncio import AsyncSession

from exnot.api.deps import require_admin
from exnot.api.schemas import ScrapeResponse
from exnot.db.engine import get_db
from exnot.db.models import User
from exnot.db.repositories import ExchangeRepository

router = APIRouter(prefix="/admin", tags=["admin"])


@router.post("/scrape/{exchange_code}", response_model=ScrapeResponse)
async def trigger_scrape(
    exchange_code: str,
    db: AsyncSession = Depends(get_db),
    user: User = Depends(require_admin),
):
    """Trigger a manual scrape for a specific exchange."""
    exchange_repo = ExchangeRepository(db)
    exchange = await exchange_repo.get_by_code(exchange_code.upper())
    if not exchange:
        raise HTTPException(status_code=404, detail=f"Exchange {exchange_code} not found")

    try:
        from exnot.workers.tasks import scrape_and_process_exchange

        result = scrape_and_process_exchange.delay(exchange_code.upper())
        return ScrapeResponse(message=f"Scrape triggered for {exchange_code}", task_id=result.id)
    except Exception as e:
        return ScrapeResponse(message=f"Failed to trigger scrape: {e}")


@router.post("/discover/{exchange_code}", response_model=ScrapeResponse)
async def trigger_discovery(
    exchange_code: str,
    force: bool = False,
    db: AsyncSession = Depends(get_db),
    user: User = Depends(require_admin),
):
    """Trigger URL discovery for a specific exchange."""
    exchange_repo = ExchangeRepository(db)
    exchange = await exchange_repo.get_by_code(exchange_code.upper())
    if not exchange:
        raise HTTPException(status_code=404, detail=f"Exchange {exchange_code} not found")

    try:
        from exnot.workers.tasks import discover_exchange_urls

        result = discover_exchange_urls.delay(exchange_code.upper(), force=force)
        return ScrapeResponse(message=f"Discovery triggered for {exchange_code}", task_id=result.id)
    except Exception as e:
        return ScrapeResponse(message=f"Failed to trigger discovery: {e}")


@router.post("/discover-all", response_model=ScrapeResponse)
async def trigger_discovery_all(
    force: bool = False,
    db: AsyncSession = Depends(get_db),
    user: User = Depends(require_admin),
):
    """Trigger URL discovery for all exchanges needing discovery."""
    try:
        from exnot.workers.tasks import discover_all_exchange_urls

        result = discover_all_exchange_urls.delay(force=force)
        return ScrapeResponse(message="Discovery triggered for all exchanges", task_id=result.id)
    except Exception as e:
        return ScrapeResponse(message=f"Failed to trigger discovery: {e}")


@router.post("/scrape-all", response_model=ScrapeResponse)
async def trigger_scrape_all(
    db: AsyncSession = Depends(get_db),
    user: User = Depends(require_admin),
):
    """Trigger a manual scrape for all active exchanges."""
    try:
        from exnot.workers.tasks import daily_fee_schedule_check

        result = daily_fee_schedule_check.delay()
        return ScrapeResponse(message="Full scrape triggered for all exchanges", task_id=result.id)
    except Exception as e:
        return ScrapeResponse(message=f"Failed to trigger scrape: {e}")
