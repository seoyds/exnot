"""Change detection tool — diff normalized fees against previous version."""

import json
import logging
from decimal import Decimal

from claude_agent_sdk import tool

logger = logging.getLogger(__name__)


@tool(
    "detect_changes",
    "Detect fee changes by comparing new normalized fees against the previous "
    "snapshot for the exchange. Returns a change report with NEW, MODIFIED, "
    "and REMOVED fee entries.",
    {"exchange_code": str, "normalized_fees_json": str},
)
async def detect_changes(args):
    try:
        from exnot.db.engine import AsyncSessionLocal
        from exnot.db.repositories import (
            ExchangeRepository,
            NormalizedFeeRepository,
            SnapshotRepository,
        )
        from exnot.differ.detector import ChangeDetector
        from exnot.normalizer.schema import (
            FeeType,
            FeeUnit,
            NormalizedFeeEntry,
            NormalizedFeeSchedule,
            OrderType,
            ParticipantType,
            SecurityClass,
        )

        exchange_code = args["exchange_code"]
        normalized_fees = json.loads(args["normalized_fees_json"])

        # Build NormalizedFeeSchedule from JSON
        new_entries = []
        for f in normalized_fees:
            try:
                entry = NormalizedFeeEntry(
                    exchange_code=exchange_code,
                    fee_code=f.get("fee_code"),
                    participant_type=ParticipantType(f["participant_type"]),
                    security_class=SecurityClass(f.get("security_class", "EQUITY")),
                    order_type=OrderType(f.get("order_type", "SIMPLE")),
                    fee_type=FeeType(f["fee_type"]),
                    fee_unit=FeeUnit(f.get("fee_unit", "PER_CONTRACT")),
                    amount=Decimal(str(f["amount"])),
                    is_rebate=f.get("is_rebate", False),
                    contra_party_type=ParticipantType(f["contra_party_type"])
                    if f.get("contra_party_type")
                    else None,
                    symbol=f.get("symbol"),
                    routing_destination=f.get("routing_destination"),
                    tier_group=f.get("tier_group"),
                    tier_number=f.get("tier_number"),
                    section_ref=f.get("section_ref"),
                    notes=f.get("notes"),
                    volume_tier=f.get("volume_tier"),
                )
                new_entries.append(entry)
            except Exception as e:
                logger.warning(f"Skipping fee entry during change detection: {e}")

        new_schedule = NormalizedFeeSchedule(
            exchange_code=exchange_code,
            exchange_name=exchange_code,
            fees=new_entries,
        )

        # Load previous schedule from DB
        old_schedule = None
        old_version = None
        new_version = 1

        async with AsyncSessionLocal() as session:
            exchange_repo = ExchangeRepository(session)
            exchange = await exchange_repo.get_by_code(exchange_code)

            if exchange:
                snapshot_repo = SnapshotRepository(session)
                latest = await snapshot_repo.get_latest(exchange.id)

                if latest:
                    old_version = latest.version
                    new_version = latest.version + 1

                    # Load previous normalized fees
                    fee_repo = NormalizedFeeRepository(session)
                    old_db_fees = await fee_repo.get_by_snapshot(latest.id)

                    if old_db_fees:
                        old_entries = []
                        for db_fee in old_db_fees:
                            try:
                                old_entry = NormalizedFeeEntry(
                                    exchange_code=exchange_code,
                                    fee_code=db_fee.fee_code,
                                    participant_type=ParticipantType(
                                        db_fee.participant_type.value
                                    ),
                                    security_class=SecurityClass(
                                        db_fee.security_class.value
                                    ),
                                    order_type=OrderType(db_fee.order_type.value),
                                    fee_type=FeeType(db_fee.fee_type.value),
                                    fee_unit=FeeUnit(db_fee.fee_unit.value),
                                    amount=Decimal(str(db_fee.amount_cents)) / 100,
                                    is_rebate=db_fee.is_rebate,
                                    contra_party_type=ParticipantType(
                                        db_fee.contra_party_type.value
                                    )
                                    if db_fee.contra_party_type
                                    else None,
                                    symbol=db_fee.symbol,
                                    volume_tier=db_fee.volume_tier,
                                    tier_number=db_fee.tier_level,
                                )
                                old_entries.append(old_entry)
                            except Exception:
                                pass

                        old_schedule = NormalizedFeeSchedule(
                            exchange_code=exchange_code,
                            exchange_name=exchange_code,
                            fees=old_entries,
                        )

        # Detect changes
        detector = ChangeDetector()
        report = detector.detect(
            old_schedule, new_schedule, old_version=old_version, new_version=new_version
        )

        # Serialize report
        changes = []
        for change in report.changes:
            changes.append(
                {
                    "change_type": change.change_type,
                    "participant_type": change.participant_type,
                    "security_class": change.security_class,
                    "order_type": change.order_type,
                    "fee_type": change.fee_type,
                    "old_amount_cents": change.old_amount_cents,
                    "new_amount_cents": change.new_amount_cents,
                    "volume_tier": change.volume_tier,
                    "description": change.description,
                }
            )

        result = {
            "exchange_code": exchange_code,
            "has_changes": report.has_changes,
            "old_version": report.old_version,
            "new_version": report.new_version,
            "summary": report.summary,
            "new_count": report.new_count,
            "modified_count": report.modified_count,
            "removed_count": report.removed_count,
            "total_changes": len(changes),
            "changes": changes,
        }

        return {
            "content": [{"type": "text", "text": json.dumps(result, default=str)}]
        }
    except Exception as e:
        logger.error(f"detect_changes failed: {e}")
        return {
            "content": [
                {"type": "text", "text": json.dumps({"error": str(e)})}
            ]
        }
