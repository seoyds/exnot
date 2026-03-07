"""DB persistence tools — save snapshots and scraped documents."""

import json
import logging
import uuid

from claude_agent_sdk import tool

logger = logging.getLogger(__name__)


@tool(
    "save_snapshot",
    "Save a fee schedule snapshot to the database, including normalized fees and "
    "detected changes. Creates the snapshot, bulk-inserts normalized fee records, "
    "and bulk-inserts change records. Returns the snapshot ID.",
    {
        "exchange_code": str,
        "normalized_fees_json": str,
        "changes_json": str,
        "document_hash": str,
    },
)
async def save_snapshot(args):
    try:
        from exnot.agents.tools.scraping import get_cached_document
        from exnot.db.engine import AsyncSessionLocal
        from exnot.db.models import (
            ChangeType,
            FeeChange,
            FeeScheduleSnapshot,
            FeeType,
            FeeUnit,
            NormalizedFee,
            OrderType,
            ParticipantType,
            SecurityClass,
            SnapshotStatus,
        )
        from exnot.db.repositories import (
            ExchangeRepository,
            FeeChangeRepository,
            NormalizedFeeRepository,
            SnapshotRepository,
        )

        exchange_code = args["exchange_code"]
        normalized_fees = json.loads(args["normalized_fees_json"])
        changes = json.loads(args["changes_json"])
        document_hash = args["document_hash"]

        cached = get_cached_document(exchange_code)
        source_url = cached["source_url"] if cached else ""

        async with AsyncSessionLocal() as session:
            # Get exchange
            exchange_repo = ExchangeRepository(session)
            exchange = await exchange_repo.get_by_code(exchange_code)
            if not exchange:
                return {
                    "content": [
                        {
                            "type": "text",
                            "text": json.dumps({"error": "Exchange not found in DB"}),
                        }
                    ]
                }

            # Get next version and previous snapshot BEFORE creating new one
            snapshot_repo = SnapshotRepository(session)
            next_version = await snapshot_repo.get_next_version(exchange.id)
            old_snapshot = await snapshot_repo.get_latest(exchange.id)
            old_snapshot_id = old_snapshot.id if old_snapshot else None

            # Create snapshot
            snapshot = FeeScheduleSnapshot(
                exchange_id=exchange.id,
                version=next_version,
                source_url=source_url,
                source_hash=document_hash,
                normalized_fees_json={"fees": normalized_fees},
                status=SnapshotStatus.NORMALIZED,
                parsing_confidence=None,
            )
            snapshot = await snapshot_repo.create(snapshot)

            # Bulk insert normalized fees
            fee_records = []
            for f in normalized_fees:
                try:
                    # Convert amount string to amount_cents
                    from decimal import Decimal

                    amount = Decimal(str(f["amount"]))
                    amount_cents = int(amount * 100)

                    fee_record = NormalizedFee(
                        snapshot_id=snapshot.id,
                        exchange_id=exchange.id,
                        fee_code=f.get("fee_code"),
                        participant_type=ParticipantType(f["participant_type"]),
                        contra_party_type=ParticipantType(f["contra_party_type"])
                        if f.get("contra_party_type")
                        else None,
                        security_class=SecurityClass(
                            f.get("security_class", "EQUITY")
                        ),
                        symbol=f.get("symbol"),
                        order_type=OrderType(f.get("order_type", "SIMPLE")),
                        fee_type=FeeType(f["fee_type"]),
                        fee_unit=FeeUnit(f.get("fee_unit", "PER_CONTRACT")),
                        amount_cents=amount_cents,
                        is_rebate=f.get("is_rebate", False),
                        routing_destination=f.get("routing_destination"),
                        section_ref=f.get("section_ref"),
                        notes=f.get("notes"),
                        volume_tier=f.get("volume_tier"),
                        exchange_fee_code=f.get("exchange_fee_code"),
                        exchange_fee_name=f.get("exchange_fee_name"),
                    )
                    fee_records.append(fee_record)
                except Exception as e:
                    logger.warning(f"Skipping fee record: {e}")

            if fee_records:
                fee_repo = NormalizedFeeRepository(session)
                await fee_repo.bulk_create(fee_records)

            # Bulk insert change records
            change_records = []

            for c in changes:
                try:
                    change_record = FeeChange(
                        exchange_id=exchange.id,
                        old_snapshot_id=old_snapshot_id,
                        new_snapshot_id=snapshot.id,
                        change_type=ChangeType(c["change_type"]),
                        participant_type=ParticipantType(c["participant_type"])
                        if c.get("participant_type")
                        else None,
                        security_class=SecurityClass(c["security_class"])
                        if c.get("security_class")
                        else None,
                        order_type=OrderType(c["order_type"])
                        if c.get("order_type")
                        else None,
                        fee_type=FeeType(c["fee_type"])
                        if c.get("fee_type")
                        else None,
                        old_amount_cents=c.get("old_amount_cents"),
                        new_amount_cents=c.get("new_amount_cents"),
                        change_description=c.get("description"),
                        notified=False,
                    )
                    change_records.append(change_record)
                except Exception as e:
                    logger.warning(f"Skipping change record: {e}")

            if change_records:
                change_repo = FeeChangeRepository(session)
                await change_repo.bulk_create(change_records)

            await session.commit()

            return {
                "content": [
                    {
                        "type": "text",
                        "text": json.dumps(
                            {
                                "snapshot_id": str(snapshot.id),
                                "version": next_version,
                                "fee_count": len(fee_records),
                                "change_count": len(change_records),
                            }
                        ),
                    }
                ]
            }
    except Exception as e:
        logger.error(f"save_snapshot failed: {e}")
        return {
            "content": [
                {"type": "text", "text": json.dumps({"error": str(e)})}
            ]
        }


@tool(
    "save_scraped_document",
    "Store the scraped document bytes in MinIO object storage and create a "
    "ScrapedDocument record linked to the snapshot. Uses the cached document "
    "from scrape_document.",
    {"exchange_code": str, "format": str, "snapshot_id": str},
)
async def save_scraped_document(args):
    try:
        from exnot.agents.tools.scraping import get_cached_document
        from exnot.db.engine import AsyncSessionLocal
        from exnot.db.models import ScrapedDocument
        from exnot.db.repositories import SnapshotRepository
        from exnot.storage.minio_client import DocumentStorage

        exchange_code = args["exchange_code"]
        doc_format = args.get("format", "html")
        snapshot_id = args["snapshot_id"]

        cached = get_cached_document(exchange_code)
        if not cached:
            return {
                "content": [
                    {
                        "type": "text",
                        "text": json.dumps(
                            {"error": "No cached document to store"}
                        ),
                    }
                ]
            }

        content_bytes = cached["content_bytes"]
        content_type = cached.get("content_type", "application/octet-stream")
        source_url = cached.get("source_url", "")
        content_hash = cached.get("content_hash", "")

        # Get version from snapshot
        async with AsyncSessionLocal() as session:
            snapshot_repo = SnapshotRepository(session)
            snapshot = await snapshot_repo.get_by_id(uuid.UUID(snapshot_id))
            version = snapshot.version if snapshot else 1

        # Store in MinIO
        ext_map = {
            "pdf": ".pdf",
            "html": ".html",
            "csv": ".csv",
            "application/pdf": ".pdf",
            "text/html": ".html",
            "text/csv": ".csv",
        }
        ext = ext_map.get(doc_format, ".bin")
        filename = f"fee_schedule{ext}"
        object_name = DocumentStorage.build_object_name(
            exchange_code, version, filename
        )

        try:
            storage = DocumentStorage()
            stored = storage.store(object_name, content_bytes, content_type)

            # Create ScrapedDocument record
            async with AsyncSessionLocal() as session:
                doc = ScrapedDocument(
                    snapshot_id=uuid.UUID(snapshot_id),
                    source_url=source_url,
                    content_type=content_type,
                    content_hash=content_hash,
                    storage_path=stored.object_name,
                    size_bytes=stored.size_bytes,
                    is_primary=True,
                )
                session.add(doc)
                await session.commit()

            return {
                "content": [
                    {
                        "type": "text",
                        "text": json.dumps(
                            {
                                "stored": True,
                                "object_name": stored.object_name,
                                "size_bytes": stored.size_bytes,
                            }
                        ),
                    }
                ]
            }
        except Exception as e:
            logger.warning(f"MinIO storage failed (non-critical): {e}")
            return {
                "content": [
                    {
                        "type": "text",
                        "text": json.dumps(
                            {
                                "stored": False,
                                "reason": f"Storage failed: {e}",
                            }
                        ),
                    }
                ]
            }
    except Exception as e:
        logger.error(f"save_scraped_document failed: {e}")
        return {
            "content": [
                {"type": "text", "text": json.dumps({"error": str(e)})}
            ]
        }
