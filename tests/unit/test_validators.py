"""Tests for fee validation logic."""

from decimal import Decimal

from exnot.normalizer.schema import (
    FeeType,
    NormalizedFeeEntry,
    NormalizedFeeSchedule,
    OrderType,
    ParticipantType,
    SecurityClass,
)
from exnot.normalizer.validators import FeeValidator


class TestFeeValidator:
    def setup_method(self):
        self.validator = FeeValidator()

    def test_valid_schedule(self, sample_schedule):
        result = self.validator.validate(sample_schedule)
        assert result.is_valid
        assert len(result.errors) == 0

    def test_empty_schedule(self):
        schedule = NormalizedFeeSchedule(exchange_code="TEST", exchange_name="Test")
        result = self.validator.validate(schedule)
        assert not result.is_valid
        assert any("No fees" in e for e in result.errors)

    def test_missing_customer_warning(self):
        fees = [
            NormalizedFeeEntry(
                exchange_code="TEST",
                participant_type=ParticipantType.MARKET_MAKER,
                security_class=SecurityClass.PENNY,
                order_type=OrderType.SIMPLE,
                fee_type=FeeType.MAKER,
                amount=Decimal("-0.20"),
                is_rebate=True,
            ),
            NormalizedFeeEntry(
                exchange_code="TEST",
                participant_type=ParticipantType.MARKET_MAKER,
                security_class=SecurityClass.PENNY,
                order_type=OrderType.SIMPLE,
                fee_type=FeeType.TAKER,
                amount=Decimal("0.45"),
                is_rebate=False,
            ),
        ]
        schedule = NormalizedFeeSchedule(
            exchange_code="TEST", exchange_name="Test", fees=fees
        )
        result = self.validator.validate(schedule)
        assert any("CUSTOMER" in w for w in result.warnings)

    def test_unusually_large_fee_warning(self):
        fees = [
            NormalizedFeeEntry(
                exchange_code="TEST",
                participant_type=ParticipantType.CUSTOMER,
                security_class=SecurityClass.PENNY,
                order_type=OrderType.SIMPLE,
                fee_type=FeeType.TAKER,
                amount=Decimal("5.00"),
                is_rebate=False,
            ),
        ]
        schedule = NormalizedFeeSchedule(
            exchange_code="TEST", exchange_name="Test", fees=fees
        )
        result = self.validator.validate(schedule)
        assert any("Unusually large fee" in w for w in result.warnings)

    def test_index_options_higher_threshold(self):
        """Index options can have higher fees without triggering warnings."""
        fees = [
            NormalizedFeeEntry(
                exchange_code="TEST",
                participant_type=ParticipantType.CUSTOMER,
                security_class=SecurityClass.INDEX,
                order_type=OrderType.SIMPLE,
                fee_type=FeeType.TAKER,
                amount=Decimal("4.50"),
                is_rebate=False,
            ),
        ]
        schedule = NormalizedFeeSchedule(
            exchange_code="TEST", exchange_name="Test", fees=fees
        )
        result = self.validator.validate(schedule)
        # Should not warn about unusually large fee for index options at 4.50
        assert not any("Unusually large fee" in w for w in result.warnings)
