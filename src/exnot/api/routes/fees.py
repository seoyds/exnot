"""Fee schedule API endpoints."""

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.ext.asyncio import AsyncSession

from exnot.api.schemas import (
    FeeListResponse,
    NormalizedFeeResponse,
    SnapshotHistoryResponse,
    SnapshotResponse,
)
from exnot.db.engine import get_db
from exnot.db.repositories import ExchangeRepository, NormalizedFeeRepository, SnapshotRepository

router = APIRouter(prefix="/exchanges/{code}/fees", tags=["fees"])


@router.get("", response_model=FeeListResponse)
async def get_fees(
    code: str,
    version: str = "latest",
    participant_type: list[str] | None = Query(default=None),
    security_class: list[str] | None = Query(default=None),
    fee_type: list[str] | None = Query(default=None),
    order_type: list[str] | None = Query(default=None),
    # V3 filters
    origin_code: list[str] | None = Query(default=None),
    liquidity_role: list[str] | None = Query(default=None),
    exec_venue: list[str] | None = Query(default=None),
    product_type: list[str] | None = Query(default=None),
    listing_type: list[str] | None = Query(default=None),
    penny_class: list[str] | None = Query(default=None),
    auction_type: list[str] | None = Query(default=None),
    db: AsyncSession = Depends(get_db),
):
    """Get normalized fees for an exchange, optionally filtered."""
    exchange_repo = ExchangeRepository(db)
    exchange = await exchange_repo.get_by_code(code.upper())
    if not exchange:
        raise HTTPException(status_code=404, detail=f"Exchange {code} not found")

    snap_repo = SnapshotRepository(db)
    if version == "latest":
        snapshot = await snap_repo.get_latest(exchange.id)
    else:
        try:
            # Find snapshot by version number
            snapshots = await snap_repo.get_history(exchange.id)
            snapshot = next((s for s in snapshots if s.version == int(version)), None)
        except ValueError:
            raise HTTPException(status_code=400, detail="Invalid version number")

    if not snapshot:
        return FeeListResponse(data=[], exchange_code=code.upper(), version=None, count=0)

    fee_repo = NormalizedFeeRepository(db)
    fees = await fee_repo.get_by_snapshot(snapshot.id)

    # Apply filters
    results = []
    for fee in fees:
        if participant_type and fee.participant_type.value not in [p.upper() for p in participant_type]:
            continue
        if security_class and fee.security_class.value not in [s.upper() for s in security_class]:
            continue
        if fee_type and fee.fee_type.value not in [f.upper() for f in fee_type]:
            continue
        if order_type and fee.order_type.value not in [o.upper() for o in order_type]:
            continue
        # V3 filters
        if origin_code and (not fee.origin_code or fee.origin_code.upper() not in [o.upper() for o in origin_code]):
            continue
        if liquidity_role and (
            not fee.liquidity_role or fee.liquidity_role.upper() not in [lr.upper() for lr in liquidity_role]
        ):
            continue
        if exec_venue and (not fee.exec_venue or fee.exec_venue.upper() not in [e.upper() for e in exec_venue]):
            continue
        if product_type and (not fee.product_type or fee.product_type.upper() not in [p.upper() for p in product_type]):
            continue
        if listing_type and (
            not fee.listing_type or fee.listing_type.upper() not in [lt.upper() for lt in listing_type]
        ):
            continue
        if penny_class and (not fee.penny_class or fee.penny_class.upper() not in [pc.upper() for pc in penny_class]):
            continue
        if auction_type and (not fee.auction_type or fee.auction_type.upper() not in [a.upper() for a in auction_type]):
            continue
        results.append(NormalizedFeeResponse.from_db_model(fee))

    return FeeListResponse(
        data=results,
        exchange_code=code.upper(),
        version=snapshot.version,
        count=len(results),
    )


@router.get("/history", response_model=SnapshotHistoryResponse)
async def get_fee_history(
    code: str,
    limit: int = Query(default=50, le=200),
    db: AsyncSession = Depends(get_db),
):
    """Get the version history of fee schedules for an exchange."""
    exchange_repo = ExchangeRepository(db)
    exchange = await exchange_repo.get_by_code(code.upper())
    if not exchange:
        raise HTTPException(status_code=404, detail=f"Exchange {code} not found")

    snap_repo = SnapshotRepository(db)
    snapshots = await snap_repo.get_history(exchange.id, limit=limit)

    results = [
        SnapshotResponse(
            id=s.id,
            exchange_code=code.upper(),
            version=s.version,
            effective_date=s.effective_date,
            source_url=s.source_url,
            source_hash=s.source_hash,
            parsing_confidence=s.parsing_confidence,
            status=s.status.value,
            milestone_tag=s.milestone_tag,
            created_at=s.created_at,
        )
        for s in snapshots
    ]

    return SnapshotHistoryResponse(data=results, exchange_code=code.upper(), count=len(results))
