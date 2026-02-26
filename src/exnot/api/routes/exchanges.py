"""Exchange CRUD API endpoints."""

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.ext.asyncio import AsyncSession

from exnot.api.schemas import ExchangeListResponse, ExchangeResponse
from exnot.db.engine import get_db
from exnot.db.repositories import ExchangeRepository, SnapshotRepository

router = APIRouter(prefix="/exchanges", tags=["exchanges"])


@router.get("", response_model=ExchangeListResponse)
async def list_exchanges(
    active_only: bool = True,
    db: AsyncSession = Depends(get_db),
):
    """List all exchanges with their latest snapshot info."""
    repo = ExchangeRepository(db)
    snap_repo = SnapshotRepository(db)

    exchanges = await repo.get_all(active_only=active_only)
    results = []
    for ex in exchanges:
        latest = await snap_repo.get_latest(ex.id)
        results.append(
            ExchangeResponse(
                id=ex.id,
                code=ex.code,
                name=ex.name,
                operator=ex.operator,
                fee_schedule_url=ex.fee_schedule_url,
                fee_schedule_format=ex.fee_schedule_format.value,
                is_active=ex.is_active,
                latest_version=latest.version if latest else None,
                latest_snapshot_date=latest.created_at if latest else None,
            )
        )

    return ExchangeListResponse(data=results, count=len(results))


@router.get("/{code}", response_model=ExchangeResponse)
async def get_exchange(
    code: str,
    db: AsyncSession = Depends(get_db),
):
    """Get a single exchange by code."""
    repo = ExchangeRepository(db)
    snap_repo = SnapshotRepository(db)

    exchange = await repo.get_by_code(code.upper())
    if not exchange:
        raise HTTPException(status_code=404, detail=f"Exchange {code} not found")

    latest = await snap_repo.get_latest(exchange.id)
    return ExchangeResponse(
        id=exchange.id,
        code=exchange.code,
        name=exchange.name,
        operator=exchange.operator,
        fee_schedule_url=exchange.fee_schedule_url,
        fee_schedule_format=exchange.fee_schedule_format.value,
        is_active=exchange.is_active,
        latest_version=latest.version if latest else None,
        latest_snapshot_date=latest.created_at if latest else None,
    )
