"""Tests for cross-exchange fee comparison."""

from decimal import Decimal

from exnot.differ.comparator import FeeComparator
from exnot.normalizer.schema import (
    FeeType,
    NormalizedFeeEntry,
    NormalizedFeeSchedule,
    OrderType,
    ParticipantType,
    SecurityClass,
)


class TestFeeComparator:
    def setup_method(self):
        self.comparator = FeeComparator()

    def _make_schedule(self, code: str, customer_maker: Decimal, customer_taker: Decimal):
        return NormalizedFeeSchedule(
            exchange_code=code,
            exchange_name=f"Test {code}",
            fees=[
                NormalizedFeeEntry(
                    exchange_code=code,
                    participant_type=ParticipantType.CUSTOMER,
                    security_class=SecurityClass.PENNY,
                    order_type=OrderType.SIMPLE,
                    fee_type=FeeType.MAKER,
                    amount=customer_maker,
                    is_rebate=customer_maker < 0,
                ),
                NormalizedFeeEntry(
                    exchange_code=code,
                    participant_type=ParticipantType.CUSTOMER,
                    security_class=SecurityClass.PENNY,
                    order_type=OrderType.SIMPLE,
                    fee_type=FeeType.TAKER,
                    amount=customer_taker,
                    is_rebate=False,
                ),
            ],
        )

    def test_compare_two_exchanges(self):
        s1 = self._make_schedule("EX_A", Decimal("-0.25"), Decimal("0.50"))
        s2 = self._make_schedule("EX_B", Decimal("-0.30"), Decimal("0.45"))

        table = self.comparator.compare([s1, s2])

        assert len(table.exchange_codes) == 2
        assert len(table.rows) == 2  # maker + taker

        # Find maker row
        maker_row = next(r for r in table.rows if r.fee_type == FeeType.MAKER)
        assert "EX_A" in maker_row.cells
        assert "EX_B" in maker_row.cells
        assert maker_row.cells["EX_A"].amount == Decimal("-0.25")
        assert maker_row.cells["EX_B"].amount == Decimal("-0.30")

        # EX_B has better (lower) maker rebate
        assert maker_row.cheapest_exchange == "EX_B"

    def test_compare_with_filter(self):
        s1 = self._make_schedule("EX_A", Decimal("-0.25"), Decimal("0.50"))
        s2 = self._make_schedule("EX_B", Decimal("-0.30"), Decimal("0.45"))

        table = self.comparator.compare([s1, s2], fee_type=FeeType.TAKER)

        assert len(table.rows) == 1
        assert table.rows[0].fee_type == FeeType.TAKER

    def test_empty_comparison(self):
        table = self.comparator.compare([])
        assert len(table.rows) == 0
        assert len(table.exchange_codes) == 0
