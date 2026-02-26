"""Validation rules for normalized fee data."""

import logging
from dataclasses import dataclass, field
from decimal import Decimal

from exnot.normalizer.schema import NormalizedFeeSchedule

logger = logging.getLogger(__name__)


@dataclass
class ValidationResult:
    is_valid: bool = True
    warnings: list[str] = field(default_factory=list)
    errors: list[str] = field(default_factory=list)

    def add_warning(self, msg: str):
        self.warnings.append(msg)
        logger.warning(f"Validation warning: {msg}")

    def add_error(self, msg: str):
        self.errors.append(msg)
        self.is_valid = False
        logger.error(f"Validation error: {msg}")


class FeeValidator:
    """Validates normalized fee schedules for completeness and correctness."""

    # Most per-contract option fees are between -$1.50 (rebate) and $2.00 (fee)
    MIN_AMOUNT = Decimal("-2.00")
    MAX_AMOUNT = Decimal("3.00")
    # Index options can have higher fees
    MAX_INDEX_AMOUNT = Decimal("5.00")

    def validate(self, schedule: NormalizedFeeSchedule) -> ValidationResult:
        result = ValidationResult()

        if not schedule.fees:
            result.add_error(f"{schedule.exchange_code}: No fees extracted")
            return result

        self._check_minimum_coverage(schedule, result)
        self._check_amount_ranges(schedule, result)
        self._check_duplicates(schedule, result)

        return result

    def _check_minimum_coverage(
        self, schedule: NormalizedFeeSchedule, result: ValidationResult
    ):
        """Check that we have minimum expected fee coverage."""
        participant_types = {f.participant_type for f in schedule.fees}
        fee_types = {f.fee_type for f in schedule.fees}

        from exnot.normalizer.schema import FeeType, ParticipantType

        if ParticipantType.CUSTOMER not in participant_types:
            result.add_warning(f"{schedule.exchange_code}: Missing CUSTOMER fees")

        if ParticipantType.MARKET_MAKER not in participant_types:
            result.add_warning(f"{schedule.exchange_code}: Missing MARKET_MAKER fees")

        if FeeType.MAKER not in fee_types:
            result.add_warning(f"{schedule.exchange_code}: Missing MAKER fees/rebates")

        if FeeType.TAKER not in fee_types:
            result.add_warning(f"{schedule.exchange_code}: Missing TAKER fees")

        if len(schedule.fees) < 4:
            result.add_warning(
                f"{schedule.exchange_code}: Only {len(schedule.fees)} fees - "
                "expected at least 4 for a minimal schedule"
            )

    def _check_amount_ranges(
        self, schedule: NormalizedFeeSchedule, result: ValidationResult
    ):
        """Check that fee amounts are within reasonable ranges."""
        for fee in schedule.fees:
            from exnot.normalizer.schema import SecurityClass

            max_amt = (
                self.MAX_INDEX_AMOUNT
                if fee.security_class == SecurityClass.INDEX
                else self.MAX_AMOUNT
            )

            if fee.amount < self.MIN_AMOUNT:
                result.add_warning(
                    f"{schedule.exchange_code}: Unusually large rebate {fee.amount} "
                    f"for {fee.participant_type.value}/{fee.fee_type.value}"
                )

            if fee.amount > max_amt:
                result.add_warning(
                    f"{schedule.exchange_code}: Unusually large fee {fee.amount} "
                    f"for {fee.participant_type.value}/{fee.fee_type.value}"
                )

    def _check_duplicates(
        self, schedule: NormalizedFeeSchedule, result: ValidationResult
    ):
        """Check for duplicate fee entries."""
        seen = set()
        for fee in schedule.fees:
            key = (
                fee.participant_type,
                fee.security_class,
                fee.order_type,
                fee.fee_type,
                fee.volume_tier,
            )
            if key in seen:
                result.add_warning(
                    f"{schedule.exchange_code}: Duplicate fee entry for "
                    f"{fee.participant_type.value}/{fee.security_class.value}/"
                    f"{fee.fee_type.value} tier={fee.volume_tier}"
                )
            seen.add(key)
