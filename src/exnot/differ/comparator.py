"""Cross-exchange fee comparison engine."""

from dataclasses import dataclass, field
from decimal import Decimal

from exnot.normalizer.schema import (
    FeeType,
    NormalizedFeeEntry,
    NormalizedFeeSchedule,
    OrderType,
    ParticipantType,
    SecurityClass,
)


@dataclass
class ComparisonCell:
    """A single cell in a comparison table."""

    exchange_code: str
    amount: Decimal
    is_rebate: bool
    volume_tier: str | None = None
    notes: str | None = None


@dataclass
class ComparisonRow:
    """A row comparing the same fee across multiple exchanges."""

    participant_type: ParticipantType
    security_class: SecurityClass
    order_type: OrderType
    fee_type: FeeType
    cells: dict[str, ComparisonCell] = field(default_factory=dict)  # keyed by exchange_code

    @property
    def cheapest_exchange(self) -> str | None:
        if not self.cells:
            return None
        return min(self.cells, key=lambda k: self.cells[k].amount)

    @property
    def most_expensive_exchange(self) -> str | None:
        if not self.cells:
            return None
        return max(self.cells, key=lambda k: self.cells[k].amount)


@dataclass
class ComparisonTable:
    """Full cross-exchange comparison result."""

    exchange_codes: list[str]
    rows: list[ComparisonRow] = field(default_factory=list)
    filters_applied: dict = field(default_factory=dict)


class FeeComparator:
    """Compares fees across multiple exchanges."""

    def compare(
        self,
        schedules: list[NormalizedFeeSchedule],
        participant_type: ParticipantType | None = None,
        security_class: SecurityClass | None = None,
        fee_type: FeeType | None = None,
        order_type: OrderType | None = None,
    ) -> ComparisonTable:
        """Compare fees across given schedules with optional filters."""
        exchange_codes = [s.exchange_code for s in schedules]
        table = ComparisonTable(
            exchange_codes=exchange_codes,
            filters_applied={
                "participant_type": participant_type.value if participant_type else None,
                "security_class": security_class.value if security_class else None,
                "fee_type": fee_type.value if fee_type else None,
                "order_type": order_type.value if order_type else None,
            },
        )

        # Collect all unique fee keys across all schedules
        all_keys: set[tuple] = set()
        fee_lookup: dict[str, dict[tuple, NormalizedFeeEntry]] = {}

        for schedule in schedules:
            fees = schedule.get_fees(participant_type, security_class, fee_type, order_type)
            lookup = {}
            for fee in fees:
                key = (fee.participant_type, fee.security_class, fee.order_type, fee.fee_type)
                # Use first match per key (base tier)
                if key not in lookup:
                    lookup[key] = fee
                    all_keys.add(key)
            fee_lookup[schedule.exchange_code] = lookup

        # Build comparison rows
        for key in sorted(all_keys, key=lambda k: (k[0].value, k[1].value, k[3].value)):
            pt, sc, ot, ft = key
            row = ComparisonRow(
                participant_type=pt,
                security_class=sc,
                order_type=ot,
                fee_type=ft,
            )
            for code in exchange_codes:
                if key in fee_lookup.get(code, {}):
                    fee = fee_lookup[code][key]
                    row.cells[code] = ComparisonCell(
                        exchange_code=code,
                        amount=fee.amount,
                        is_rebate=fee.is_rebate,
                        volume_tier=fee.volume_tier,
                        notes=fee.notes,
                    )
            table.rows.append(row)

        return table
