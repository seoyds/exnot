"""Cross-exchange fee comparison API endpoints."""

from fastapi import APIRouter, Depends, Query
from sqlalchemy.ext.asyncio import AsyncSession

from exnot.api.schemas import ComparisonCellResponse, ComparisonResponse, ComparisonRowResponse
from exnot.db.engine import get_db
from exnot.db.repositories import ExchangeRepository, NormalizedFeeRepository, SnapshotRepository
from exnot.differ.comparator import FeeComparator
from exnot.normalizer.schema import (
    FeeType,
    NormalizedFeeEntry,
    NormalizedFeeSchedule,
    OrderType,
    ParticipantType,
    SecurityClass,
)

router = APIRouter(prefix="/compare", tags=["comparison"])


@router.get("", response_model=ComparisonResponse)
async def compare_exchanges(
    exchanges: list[str] = Query(description="Exchange codes to compare"),
    participant_type: str | None = Query(default=None),
    security_class: str | None = Query(default=None),
    fee_type: str | None = Query(default=None),
    order_type: str | None = Query(default=None),
    db: AsyncSession = Depends(get_db),
):
    """Compare fees across multiple exchanges."""
    exchange_repo = ExchangeRepository(db)
    snap_repo = SnapshotRepository(db)
    fee_repo = NormalizedFeeRepository(db)

    schedules: list[NormalizedFeeSchedule] = []

    for code in exchanges:
        exchange = await exchange_repo.get_by_code(code.upper())
        if not exchange:
            continue

        snapshot = await snap_repo.get_latest(exchange.id)
        if not snapshot:
            continue

        fees = await fee_repo.get_by_snapshot(snapshot.id)
        from decimal import Decimal

        normalized_fees = [
            NormalizedFeeEntry(
                exchange_code=code.upper(),
                participant_type=ParticipantType(f.participant_type.value),
                security_class=SecurityClass(f.security_class.value),
                order_type=OrderType(f.order_type.value),
                fee_type=FeeType(f.fee_type.value),
                amount=Decimal(f.amount_cents) / Decimal(10000),
                is_rebate=f.is_rebate,
                volume_tier=f.volume_tier,
                effective_date=f.effective_date,
                notes=f.notes,
            )
            for f in fees
        ]

        schedules.append(
            NormalizedFeeSchedule(
                exchange_code=code.upper(),
                exchange_name=exchange.name,
                effective_date=snapshot.effective_date,
                fees=normalized_fees,
            )
        )

    # Apply filters
    pt = ParticipantType(participant_type.upper()) if participant_type else None
    sc = SecurityClass(security_class.upper()) if security_class else None
    ft = FeeType(fee_type.upper()) if fee_type else None
    ot = OrderType(order_type.upper()) if order_type else None

    comparator = FeeComparator()
    table = comparator.compare(schedules, pt, sc, ft, ot)

    rows = []
    for row in table.rows:
        cells = {}
        for code, cell in row.cells.items():
            cells[code] = ComparisonCellResponse(
                exchange_code=cell.exchange_code,
                amount=cell.amount,
                is_rebate=cell.is_rebate,
                volume_tier=cell.volume_tier,
            )
        rows.append(
            ComparisonRowResponse(
                participant_type=row.participant_type.value,
                security_class=row.security_class.value,
                order_type=row.order_type.value,
                fee_type=row.fee_type.value,
                exchanges=cells,
                cheapest=row.cheapest_exchange,
                most_expensive=row.most_expensive_exchange,
            )
        )

    return ComparisonResponse(
        exchange_codes=table.exchange_codes,
        rows=rows,
        filters=table.filters_applied,
    )
