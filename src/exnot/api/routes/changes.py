"""Fee change history API endpoints."""

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.ext.asyncio import AsyncSession

from exnot.api.schemas import FeeChangeResponse, RecentChangesResponse
from exnot.db.engine import get_db
from exnot.db.repositories import ExchangeRepository, FeeChangeRepository

router = APIRouter(prefix="/changes", tags=["changes"])


@router.get("/recent", response_model=RecentChangesResponse)
async def get_recent_changes(
    days: int = Query(default=7, ge=1, le=90),
    limit: int = Query(default=100, le=500),
    db: AsyncSession = Depends(get_db),
):
    """Get recent fee changes across all exchanges."""
    repo = FeeChangeRepository(db)
    changes = await repo.get_recent(days=days, limit=limit)

    results = [FeeChangeResponse.from_db_model(c) for c in changes]
    return RecentChangesResponse(data=results, count=len(results))


@router.get("/{exchange_code}", response_model=RecentChangesResponse)
async def get_exchange_changes(
    exchange_code: str,
    limit: int = Query(default=50, le=200),
    db: AsyncSession = Depends(get_db),
):
    """Get fee changes for a specific exchange."""
    exchange_repo = ExchangeRepository(db)
    exchange = await exchange_repo.get_by_code(exchange_code.upper())
    if not exchange:
        raise HTTPException(status_code=404, detail=f"Exchange {exchange_code} not found")

    repo = FeeChangeRepository(db)
    changes = await repo.get_for_exchange(exchange.id, limit=limit)

    results = [FeeChangeResponse.from_db_model(c) for c in changes]
    return RecentChangesResponse(data=results, count=len(results))
