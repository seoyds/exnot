"""Change detection between fee schedule versions."""

import logging
from dataclasses import dataclass, field

from exnot.normalizer.schema import NormalizedFeeEntry, NormalizedFeeSchedule

logger = logging.getLogger(__name__)


@dataclass
class FeeChangeEntry:
    """A single detected fee change."""

    change_type: str  # NEW, MODIFIED, REMOVED
    participant_type: str | None = None
    security_class: str | None = None
    order_type: str | None = None
    fee_type: str | None = None
    old_amount_cents: int | None = None
    new_amount_cents: int | None = None
    volume_tier: str | None = None
    description: str = ""


@dataclass
class ChangeReport:
    """Report of all changes between two fee schedule versions."""

    exchange_code: str
    old_version: int | None
    new_version: int
    changes: list[FeeChangeEntry] = field(default_factory=list)
    summary: str = ""

    @property
    def has_changes(self) -> bool:
        return len(self.changes) > 0

    @property
    def new_count(self) -> int:
        return sum(1 for c in self.changes if c.change_type == "NEW")

    @property
    def modified_count(self) -> int:
        return sum(1 for c in self.changes if c.change_type == "MODIFIED")

    @property
    def removed_count(self) -> int:
        return sum(1 for c in self.changes if c.change_type == "REMOVED")


def _fee_key(fee: NormalizedFeeEntry) -> tuple:
    """Create a comparison key for a fee entry.

    Uses V2 dimensions (fee_code, contra_party, symbol, tier_number) when available,
    falling back to V1 volume_tier for backward compatibility.
    """
    return (
        fee.participant_type,
        fee.security_class,
        fee.order_type,
        fee.fee_type,
        fee.fee_code or "",
        fee.contra_party_type or "",
        fee.symbol or "",
        fee.tier_number if fee.tier_number is not None else (fee.volume_tier or ""),
    )


class ChangeDetector:
    """Detects changes between two normalized fee schedules."""

    def detect(
        self,
        old_schedule: NormalizedFeeSchedule | None,
        new_schedule: NormalizedFeeSchedule,
        old_version: int | None = None,
        new_version: int = 1,
    ) -> ChangeReport:
        """Compare old and new schedules, returning detected changes."""
        report = ChangeReport(
            exchange_code=new_schedule.exchange_code,
            old_version=old_version,
            new_version=new_version,
        )

        if old_schedule is None:
            # First version - everything is new
            for fee in new_schedule.fees:
                report.changes.append(
                    FeeChangeEntry(
                        change_type="NEW",
                        participant_type=fee.participant_type.value,
                        security_class=fee.security_class.value,
                        order_type=fee.order_type.value,
                        fee_type=fee.fee_type.value,
                        new_amount_cents=fee.amount_cents,
                        volume_tier=fee.volume_tier,
                        description=f"New fee: {fee.fee_type.value} for {fee.participant_type.value}",
                    )
                )
            report.summary = f"Initial fee schedule with {len(new_schedule.fees)} fee entries."
            return report

        # Build lookup maps
        old_map = {_fee_key(f): f for f in old_schedule.fees}
        new_map = {_fee_key(f): f for f in new_schedule.fees}

        old_keys = set(old_map.keys())
        new_keys = set(new_map.keys())

        # New fees (in new but not old)
        for key in new_keys - old_keys:
            fee = new_map[key]
            report.changes.append(
                FeeChangeEntry(
                    change_type="NEW",
                    participant_type=fee.participant_type.value,
                    security_class=fee.security_class.value,
                    order_type=fee.order_type.value,
                    fee_type=fee.fee_type.value,
                    new_amount_cents=fee.amount_cents,
                    volume_tier=fee.volume_tier,
                    description=f"New {fee.fee_type.value} fee for {fee.participant_type.value}: ${fee.amount}",
                )
            )

        # Removed fees (in old but not new)
        for key in old_keys - new_keys:
            fee = old_map[key]
            report.changes.append(
                FeeChangeEntry(
                    change_type="REMOVED",
                    participant_type=fee.participant_type.value,
                    security_class=fee.security_class.value,
                    order_type=fee.order_type.value,
                    fee_type=fee.fee_type.value,
                    old_amount_cents=fee.amount_cents,
                    volume_tier=fee.volume_tier,
                    description=f"Removed {fee.fee_type.value} fee for {fee.participant_type.value}",
                )
            )

        # Modified fees (in both but different amounts)
        for key in old_keys & new_keys:
            old_fee = old_map[key]
            new_fee = new_map[key]
            if old_fee.amount_cents != new_fee.amount_cents:
                direction = "increased" if new_fee.amount > old_fee.amount else "decreased"
                report.changes.append(
                    FeeChangeEntry(
                        change_type="MODIFIED",
                        participant_type=new_fee.participant_type.value,
                        security_class=new_fee.security_class.value,
                        order_type=new_fee.order_type.value,
                        fee_type=new_fee.fee_type.value,
                        old_amount_cents=old_fee.amount_cents,
                        new_amount_cents=new_fee.amount_cents,
                        volume_tier=new_fee.volume_tier,
                        description=(
                            f"{new_fee.fee_type.value} fee for {new_fee.participant_type.value} "
                            f"{direction} from ${old_fee.amount} to ${new_fee.amount}"
                        ),
                    )
                )

        # Generate summary
        if report.has_changes:
            parts = []
            if report.new_count:
                parts.append(f"{report.new_count} new")
            if report.modified_count:
                parts.append(f"{report.modified_count} modified")
            if report.removed_count:
                parts.append(f"{report.removed_count} removed")
            report.summary = f"Fee schedule changes: {', '.join(parts)} fee entries."
        else:
            report.summary = "No fee changes detected."

        logger.info(f"[{new_schedule.exchange_code}] Change detection: {report.summary}")
        return report
