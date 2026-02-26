"""Test configuration and shared fixtures."""

from datetime import date
from decimal import Decimal

import pytest

from exnot.normalizer.schema import (
    FeeType,
    NormalizedFeeEntry,
    NormalizedFeeSchedule,
    OrderType,
    ParticipantType,
    SecurityClass,
)


@pytest.fixture
def sample_fee_entry():
    """A sample normalized fee entry for testing."""
    return NormalizedFeeEntry(
        exchange_code="CBOE_C1",
        participant_type=ParticipantType.CUSTOMER,
        security_class=SecurityClass.PENNY,
        order_type=OrderType.SIMPLE,
        fee_type=FeeType.MAKER,
        amount=Decimal("-0.25"),
        is_rebate=True,
        effective_date=date(2026, 1, 1),
    )


@pytest.fixture
def sample_schedule():
    """A sample normalized fee schedule with multiple entries."""
    fees = [
        NormalizedFeeEntry(
            exchange_code="CBOE_C1",
            participant_type=ParticipantType.CUSTOMER,
            security_class=SecurityClass.PENNY,
            order_type=OrderType.SIMPLE,
            fee_type=FeeType.MAKER,
            amount=Decimal("-0.25"),
            is_rebate=True,
        ),
        NormalizedFeeEntry(
            exchange_code="CBOE_C1",
            participant_type=ParticipantType.CUSTOMER,
            security_class=SecurityClass.PENNY,
            order_type=OrderType.SIMPLE,
            fee_type=FeeType.TAKER,
            amount=Decimal("0.50"),
            is_rebate=False,
        ),
        NormalizedFeeEntry(
            exchange_code="CBOE_C1",
            participant_type=ParticipantType.MARKET_MAKER,
            security_class=SecurityClass.PENNY,
            order_type=OrderType.SIMPLE,
            fee_type=FeeType.MAKER,
            amount=Decimal("-0.20"),
            is_rebate=True,
        ),
        NormalizedFeeEntry(
            exchange_code="CBOE_C1",
            participant_type=ParticipantType.MARKET_MAKER,
            security_class=SecurityClass.PENNY,
            order_type=OrderType.SIMPLE,
            fee_type=FeeType.TAKER,
            amount=Decimal("0.45"),
            is_rebate=False,
        ),
        NormalizedFeeEntry(
            exchange_code="CBOE_C1",
            participant_type=ParticipantType.CUSTOMER,
            security_class=SecurityClass.NON_PENNY,
            order_type=OrderType.SIMPLE,
            fee_type=FeeType.MAKER,
            amount=Decimal("-0.40"),
            is_rebate=True,
        ),
        NormalizedFeeEntry(
            exchange_code="CBOE_C1",
            participant_type=ParticipantType.CUSTOMER,
            security_class=SecurityClass.NON_PENNY,
            order_type=OrderType.SIMPLE,
            fee_type=FeeType.TAKER,
            amount=Decimal("0.85"),
            is_rebate=False,
        ),
    ]

    return NormalizedFeeSchedule(
        exchange_code="CBOE_C1",
        exchange_name="Cboe Options Exchange",
        effective_date=date(2026, 1, 1),
        fees=fees,
        parsing_confidence=0.95,
    )


@pytest.fixture
def sample_schedule_updated():
    """An updated version of the sample schedule with some changes."""
    fees = [
        # Customer penny maker changed from -0.25 to -0.28 (more rebate)
        NormalizedFeeEntry(
            exchange_code="CBOE_C1",
            participant_type=ParticipantType.CUSTOMER,
            security_class=SecurityClass.PENNY,
            order_type=OrderType.SIMPLE,
            fee_type=FeeType.MAKER,
            amount=Decimal("-0.28"),
            is_rebate=True,
        ),
        # Customer penny taker unchanged
        NormalizedFeeEntry(
            exchange_code="CBOE_C1",
            participant_type=ParticipantType.CUSTOMER,
            security_class=SecurityClass.PENNY,
            order_type=OrderType.SIMPLE,
            fee_type=FeeType.TAKER,
            amount=Decimal("0.50"),
            is_rebate=False,
        ),
        # MM penny maker unchanged
        NormalizedFeeEntry(
            exchange_code="CBOE_C1",
            participant_type=ParticipantType.MARKET_MAKER,
            security_class=SecurityClass.PENNY,
            order_type=OrderType.SIMPLE,
            fee_type=FeeType.MAKER,
            amount=Decimal("-0.20"),
            is_rebate=True,
        ),
        # MM penny taker increased from 0.45 to 0.48
        NormalizedFeeEntry(
            exchange_code="CBOE_C1",
            participant_type=ParticipantType.MARKET_MAKER,
            security_class=SecurityClass.PENNY,
            order_type=OrderType.SIMPLE,
            fee_type=FeeType.TAKER,
            amount=Decimal("0.48"),
            is_rebate=False,
        ),
        # Customer non-penny maker unchanged
        NormalizedFeeEntry(
            exchange_code="CBOE_C1",
            participant_type=ParticipantType.CUSTOMER,
            security_class=SecurityClass.NON_PENNY,
            order_type=OrderType.SIMPLE,
            fee_type=FeeType.MAKER,
            amount=Decimal("-0.40"),
            is_rebate=True,
        ),
        # Customer non-penny taker unchanged
        NormalizedFeeEntry(
            exchange_code="CBOE_C1",
            participant_type=ParticipantType.CUSTOMER,
            security_class=SecurityClass.NON_PENNY,
            order_type=OrderType.SIMPLE,
            fee_type=FeeType.TAKER,
            amount=Decimal("0.85"),
            is_rebate=False,
        ),
        # NEW: Complex order fee
        NormalizedFeeEntry(
            exchange_code="CBOE_C1",
            participant_type=ParticipantType.CUSTOMER,
            security_class=SecurityClass.PENNY,
            order_type=OrderType.COMPLEX,
            fee_type=FeeType.TAKER,
            amount=Decimal("0.40"),
            is_rebate=False,
        ),
    ]

    return NormalizedFeeSchedule(
        exchange_code="CBOE_C1",
        exchange_name="Cboe Options Exchange",
        effective_date=date(2026, 2, 1),
        fees=fees,
        parsing_confidence=0.93,
    )
