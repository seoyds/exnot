import uuid
from datetime import datetime

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from exnot.db.models import (
    AgentEvent,
    AgentRun,
    AgentRunStatus,
    BillingCode,
    CanonicalFee,
    DocumentCategory,
    DocumentStatus,
    Exchange,
    ExchangeDocument,
    ExchangeProfile,
    FeeChange,
    FeeScheduleSnapshot,
    FeeType,
    NormalizedFee,
    ScrapedDocument,
    ScrapeLog,
    Subscriber,
    User,
)


class ExchangeRepository:
    def __init__(self, session: AsyncSession):
        self.session = session

    async def get_all(self, active_only: bool = True) -> list[Exchange]:
        stmt = select(Exchange)
        if active_only:
            stmt = stmt.where(Exchange.is_active.is_(True))
        stmt = stmt.order_by(Exchange.operator, Exchange.name)
        result = await self.session.execute(stmt)
        return list(result.scalars().all())

    async def get_by_code(self, code: str) -> Exchange | None:
        stmt = select(Exchange).where(Exchange.code == code)
        result = await self.session.execute(stmt)
        return result.scalar_one_or_none()

    async def get_by_id(self, exchange_id: uuid.UUID) -> Exchange | None:
        stmt = select(Exchange).where(Exchange.id == exchange_id)
        result = await self.session.execute(stmt)
        return result.scalar_one_or_none()

    async def create(self, exchange: Exchange) -> Exchange:
        self.session.add(exchange)
        await self.session.flush()
        return exchange

    async def upsert(self, exchange: Exchange) -> Exchange:
        existing = await self.get_by_code(exchange.code)
        if existing:
            existing.name = exchange.name
            existing.operator = exchange.operator
            existing.fee_schedule_url = exchange.fee_schedule_url
            existing.alternate_urls = exchange.alternate_urls
            existing.fee_schedule_format = exchange.fee_schedule_format
            existing.scraper_type = exchange.scraper_type
            existing.parser_hints = exchange.parser_hints
            existing.is_active = exchange.is_active
            await self.session.flush()
            return existing
        return await self.create(exchange)


class SnapshotRepository:
    def __init__(self, session: AsyncSession):
        self.session = session

    async def get_latest(self, exchange_id: uuid.UUID) -> FeeScheduleSnapshot | None:
        stmt = (
            select(FeeScheduleSnapshot)
            .where(FeeScheduleSnapshot.exchange_id == exchange_id)
            .order_by(FeeScheduleSnapshot.version.desc())
            .limit(1)
        )
        result = await self.session.execute(stmt)
        return result.scalar_one_or_none()

    async def get_latest_hash(self, exchange_id: uuid.UUID) -> str | None:
        snapshot = await self.get_latest(exchange_id)
        return snapshot.source_hash if snapshot else None

    async def get_next_version(self, exchange_id: uuid.UUID) -> int:
        stmt = select(func.coalesce(func.max(FeeScheduleSnapshot.version), 0)).where(
            FeeScheduleSnapshot.exchange_id == exchange_id
        )
        result = await self.session.execute(stmt)
        return result.scalar() + 1

    async def create(self, snapshot: FeeScheduleSnapshot) -> FeeScheduleSnapshot:
        self.session.add(snapshot)
        await self.session.flush()
        return snapshot

    async def get_by_id(self, snapshot_id: uuid.UUID) -> FeeScheduleSnapshot | None:
        stmt = select(FeeScheduleSnapshot).where(FeeScheduleSnapshot.id == snapshot_id)
        result = await self.session.execute(stmt)
        return result.scalar_one_or_none()

    async def get_history(self, exchange_id: uuid.UUID, limit: int = 50) -> list[FeeScheduleSnapshot]:
        stmt = (
            select(FeeScheduleSnapshot)
            .where(FeeScheduleSnapshot.exchange_id == exchange_id)
            .order_by(FeeScheduleSnapshot.version.desc())
            .limit(limit)
        )
        result = await self.session.execute(stmt)
        return list(result.scalars().all())


class NormalizedFeeRepository:
    def __init__(self, session: AsyncSession):
        self.session = session

    async def get_by_snapshot(self, snapshot_id: uuid.UUID) -> list[NormalizedFee]:
        stmt = (
            select(NormalizedFee)
            .where(NormalizedFee.snapshot_id == snapshot_id)
            .options(selectinload(NormalizedFee.tier), selectinload(NormalizedFee.canonical_fee))
            .order_by(
                NormalizedFee.participant_type,
                NormalizedFee.security_class,
                NormalizedFee.fee_type,
            )
        )
        result = await self.session.execute(stmt)
        return list(result.scalars().all())

    async def get_latest_for_exchange(self, exchange_id: uuid.UUID) -> list[NormalizedFee]:
        latest_snapshot = await SnapshotRepository(self.session).get_latest(exchange_id)
        if not latest_snapshot:
            return []
        return await self.get_by_snapshot(latest_snapshot.id)

    async def bulk_create(self, fees: list[NormalizedFee]) -> list[NormalizedFee]:
        self.session.add_all(fees)
        await self.session.flush()
        return fees


class FeeChangeRepository:
    def __init__(self, session: AsyncSession):
        self.session = session

    async def create(self, change: FeeChange) -> FeeChange:
        self.session.add(change)
        await self.session.flush()
        return change

    async def bulk_create(self, changes: list[FeeChange]) -> list[FeeChange]:
        self.session.add_all(changes)
        await self.session.flush()
        return changes

    async def get_recent(self, days: int = 7, limit: int = 100) -> list[FeeChange]:
        from datetime import timedelta

        cutoff = datetime.utcnow() - timedelta(days=days)
        stmt = (
            select(FeeChange)
            .where(FeeChange.detected_at >= cutoff)
            .options(selectinload(FeeChange.exchange))
            .order_by(FeeChange.detected_at.desc())
            .limit(limit)
        )
        result = await self.session.execute(stmt)
        return list(result.scalars().all())

    async def get_unnotified(self) -> list[FeeChange]:
        stmt = (
            select(FeeChange)
            .where(FeeChange.notified.is_(False))
            .options(selectinload(FeeChange.exchange))
            .order_by(FeeChange.detected_at.asc())
        )
        result = await self.session.execute(stmt)
        return list(result.scalars().all())

    async def get_for_exchange(self, exchange_id: uuid.UUID, limit: int = 50) -> list[FeeChange]:
        stmt = (
            select(FeeChange)
            .where(FeeChange.exchange_id == exchange_id)
            .order_by(FeeChange.detected_at.desc())
            .limit(limit)
        )
        result = await self.session.execute(stmt)
        return list(result.scalars().all())


class UserRepository:
    def __init__(self, session: AsyncSession):
        self.session = session

    async def get_by_email(self, email: str) -> User | None:
        stmt = select(User).where(User.email == email)
        result = await self.session.execute(stmt)
        return result.scalar_one_or_none()

    async def get_by_username(self, username: str) -> User | None:
        stmt = select(User).where(User.username == username)
        result = await self.session.execute(stmt)
        return result.scalar_one_or_none()

    async def create(self, user: User) -> User:
        self.session.add(user)
        await self.session.flush()
        return user


class SubscriberRepository:
    def __init__(self, session: AsyncSession):
        self.session = session

    async def get_all_active(self) -> list[Subscriber]:
        stmt = select(Subscriber).where(Subscriber.is_active.is_(True))
        result = await self.session.execute(stmt)
        return list(result.scalars().all())

    async def get_by_email(self, email: str) -> Subscriber | None:
        stmt = select(Subscriber).where(Subscriber.email == email)
        result = await self.session.execute(stmt)
        return result.scalar_one_or_none()

    async def create(self, subscriber: Subscriber) -> Subscriber:
        self.session.add(subscriber)
        await self.session.flush()
        return subscriber


class ScrapedDocumentRepository:
    def __init__(self, session: AsyncSession):
        self.session = session

    async def get_by_id(self, doc_id: uuid.UUID) -> ScrapedDocument | None:
        stmt = select(ScrapedDocument).where(ScrapedDocument.id == doc_id)
        result = await self.session.execute(stmt)
        return result.scalar_one_or_none()

    async def get_by_snapshot(self, snapshot_id: uuid.UUID) -> list[ScrapedDocument]:
        stmt = (
            select(ScrapedDocument)
            .where(ScrapedDocument.snapshot_id == snapshot_id)
            .order_by(ScrapedDocument.is_primary.desc(), ScrapedDocument.fetched_at)
        )
        result = await self.session.execute(stmt)
        return list(result.scalars().all())

    async def get_primary(self, snapshot_id: uuid.UUID) -> ScrapedDocument | None:
        stmt = (
            select(ScrapedDocument)
            .where(ScrapedDocument.snapshot_id == snapshot_id, ScrapedDocument.is_primary.is_(True))
            .limit(1)
        )
        result = await self.session.execute(stmt)
        return result.scalar_one_or_none()


class ScrapeLogRepository:
    def __init__(self, session: AsyncSession):
        self.session = session

    async def create(self, log: ScrapeLog) -> ScrapeLog:
        self.session.add(log)
        await self.session.flush()
        return log

    async def get_recent(self, exchange_id: uuid.UUID, limit: int = 10) -> list[ScrapeLog]:
        stmt = (
            select(ScrapeLog)
            .where(ScrapeLog.exchange_id == exchange_id)
            .order_by(ScrapeLog.started_at.desc())
            .limit(limit)
        )
        result = await self.session.execute(stmt)
        return list(result.scalars().all())


class ExchangeProfileRepository:
    """Data access for exchange profiles."""

    def __init__(self, session: AsyncSession):
        self.session = session

    async def get_by_exchange_id(self, exchange_id: uuid.UUID) -> ExchangeProfile | None:
        stmt = select(ExchangeProfile).where(ExchangeProfile.exchange_id == exchange_id)
        result = await self.session.execute(stmt)
        return result.scalar_one_or_none()

    async def get_by_exchange_code(self, code: str) -> ExchangeProfile | None:
        stmt = select(ExchangeProfile).join(Exchange).where(Exchange.code == code)
        result = await self.session.execute(stmt)
        return result.scalar_one_or_none()

    async def create(self, profile: ExchangeProfile) -> ExchangeProfile:
        self.session.add(profile)
        await self.session.flush()
        return profile

    async def update(self, profile: ExchangeProfile) -> ExchangeProfile:
        await self.session.flush()
        return profile


class AgentRunRepository:
    def __init__(self, session: AsyncSession):
        self.session = session

    async def create(self, run: AgentRun) -> AgentRun:
        self.session.add(run)
        await self.session.flush()
        return run

    async def get_by_id(self, run_id: uuid.UUID) -> AgentRun | None:
        stmt = select(AgentRun).where(AgentRun.id == run_id).options(selectinload(AgentRun.exchange))
        result = await self.session.execute(stmt)
        return result.scalar_one_or_none()

    async def get_active(self) -> list[AgentRun]:
        stmt = (
            select(AgentRun)
            .where(AgentRun.status == AgentRunStatus.RUNNING)
            .options(selectinload(AgentRun.exchange))
            .order_by(AgentRun.started_at.desc())
        )
        result = await self.session.execute(stmt)
        return list(result.scalars().all())

    async def get_recent(self, limit: int = 50) -> list[AgentRun]:
        stmt = (
            select(AgentRun).options(selectinload(AgentRun.exchange)).order_by(AgentRun.started_at.desc()).limit(limit)
        )
        result = await self.session.execute(stmt)
        return list(result.scalars().all())


class AgentEventRepository:
    def __init__(self, session: AsyncSession):
        self.session = session

    async def create(self, event: AgentEvent) -> AgentEvent:
        self.session.add(event)
        await self.session.flush()
        return event

    async def get_for_run(self, run_id: uuid.UUID) -> list[AgentEvent]:
        stmt = select(AgentEvent).where(AgentEvent.run_id == run_id).order_by(AgentEvent.seq)
        result = await self.session.execute(stmt)
        return list(result.scalars().all())


class ExchangeDocumentRepository:
    def __init__(self, session: AsyncSession):
        self.session = session

    async def get_by_exchange(
        self,
        exchange_id: uuid.UUID,
        category: DocumentCategory | None = None,
        status: DocumentStatus | None = None,
    ) -> list[ExchangeDocument]:
        stmt = select(ExchangeDocument).where(ExchangeDocument.exchange_id == exchange_id)
        if category:
            stmt = stmt.where(ExchangeDocument.doc_category == category)
        if status:
            stmt = stmt.where(ExchangeDocument.status == status)
        stmt = stmt.order_by(
            ExchangeDocument.is_pinned.desc(),
            ExchangeDocument.is_primary.desc(),
            ExchangeDocument.discovered_at.desc(),
        )
        result = await self.session.execute(stmt)
        return list(result.scalars().all())

    async def get_approved_for_exchange(
        self, exchange_id: uuid.UUID, category: DocumentCategory | None = None
    ) -> list[ExchangeDocument]:
        return await self.get_by_exchange(exchange_id, category=category, status=DocumentStatus.APPROVED)

    async def get_pinned_for_exchange(self, exchange_id: uuid.UUID) -> list[ExchangeDocument]:
        stmt = (
            select(ExchangeDocument)
            .where(
                ExchangeDocument.exchange_id == exchange_id,
                ExchangeDocument.is_pinned == True,  # noqa: E712
                ExchangeDocument.status == DocumentStatus.APPROVED,
            )
            .order_by(ExchangeDocument.is_primary.desc())
        )
        result = await self.session.execute(stmt)
        return list(result.scalars().all())

    async def get_pending_review(self, exchange_id: uuid.UUID | None = None) -> list[ExchangeDocument]:
        stmt = select(ExchangeDocument).where(ExchangeDocument.status == DocumentStatus.CLASSIFIED)
        if exchange_id:
            stmt = stmt.where(ExchangeDocument.exchange_id == exchange_id)
        stmt = stmt.order_by(ExchangeDocument.discovered_at.desc())
        result = await self.session.execute(stmt)
        return list(result.scalars().all())

    async def get_by_id(self, doc_id: uuid.UUID) -> ExchangeDocument | None:
        stmt = select(ExchangeDocument).where(ExchangeDocument.id == doc_id)
        result = await self.session.execute(stmt)
        return result.scalar_one_or_none()

    async def get_by_url(self, exchange_id: uuid.UUID, source_url: str) -> ExchangeDocument | None:
        stmt = select(ExchangeDocument).where(
            ExchangeDocument.exchange_id == exchange_id,
            ExchangeDocument.source_url == source_url,
        )
        result = await self.session.execute(stmt)
        return result.scalar_one_or_none()

    async def create(self, doc: ExchangeDocument) -> ExchangeDocument:
        self.session.add(doc)
        await self.session.flush()
        return doc

    async def update_status(
        self,
        doc_id: uuid.UUID,
        status: DocumentStatus,
        approved_by: uuid.UUID | None = None,
        admin_notes: str | None = None,
    ) -> ExchangeDocument | None:
        stmt = select(ExchangeDocument).where(ExchangeDocument.id == doc_id)
        result = await self.session.execute(stmt)
        doc = result.scalar_one_or_none()
        if doc:
            doc.status = status
            if status == DocumentStatus.APPROVED and approved_by:
                doc.approved_at = datetime.utcnow()
                doc.approved_by = approved_by
            if admin_notes is not None:
                doc.admin_notes = admin_notes
            await self.session.flush()
        return doc

    async def upsert_by_url(
        self,
        exchange_id: uuid.UUID,
        source_url: str,
        defaults: dict,
    ) -> tuple[ExchangeDocument, bool]:
        """Insert or update by exchange_id+source_url. Returns (doc, created)."""
        existing = await self.get_by_url(exchange_id, source_url)
        if existing:
            for key, val in defaults.items():
                if hasattr(existing, key):
                    setattr(existing, key, val)
            existing.last_seen_at = datetime.utcnow()
            await self.session.flush()
            return existing, False
        doc = ExchangeDocument(exchange_id=exchange_id, source_url=source_url, **defaults)
        self.session.add(doc)
        await self.session.flush()
        return doc, True


class CanonicalFeeRepository:
    def __init__(self, session: AsyncSession):
        self.session = session

    async def get_all(self) -> list[CanonicalFee]:
        stmt = select(CanonicalFee).order_by(CanonicalFee.category, CanonicalFee.canonical_code)
        result = await self.session.execute(stmt)
        return list(result.scalars().all())

    async def get_by_code(self, canonical_code: str) -> CanonicalFee | None:
        stmt = select(CanonicalFee).where(CanonicalFee.canonical_code == canonical_code)
        result = await self.session.execute(stmt)
        return result.scalar_one_or_none()

    async def get_by_id(self, fee_id: int) -> CanonicalFee | None:
        stmt = select(CanonicalFee).where(CanonicalFee.id == fee_id)
        result = await self.session.execute(stmt)
        return result.scalar_one_or_none()

    async def seed_from_yaml(self, yaml_path: str) -> int:
        """Load canonical fees from YAML, upsert by canonical_code. Returns count of new entries."""
        from pathlib import Path

        import yaml

        data = yaml.safe_load(Path(yaml_path).read_text())
        created = 0
        for entry in data["fees"]:
            existing = await self.get_by_code(entry["canonical_code"])
            if not existing:
                fee = CanonicalFee(
                    canonical_code=entry["canonical_code"],
                    display_name=entry["display_name"],
                    fee_type=FeeType[entry["fee_type"]],
                    description=entry.get("description"),
                    category=entry.get("category"),
                )
                self.session.add(fee)
                created += 1
        await self.session.flush()
        return created


class BillingCodeRepository:
    def __init__(self, session: AsyncSession):
        self.session = session

    async def get_by_exchange(self, exchange_id: uuid.UUID) -> list[BillingCode]:
        stmt = select(BillingCode).where(BillingCode.exchange_id == exchange_id).order_by(BillingCode.code)
        result = await self.session.execute(stmt)
        return list(result.scalars().all())

    async def upsert(self, exchange_id: uuid.UUID, code: str, defaults: dict) -> tuple[BillingCode, bool]:
        stmt = select(BillingCode).where(
            BillingCode.exchange_id == exchange_id,
            BillingCode.code == code,
        )
        result = await self.session.execute(stmt)
        existing = result.scalar_one_or_none()
        if existing:
            for key, val in defaults.items():
                if hasattr(existing, key):
                    setattr(existing, key, val)
            await self.session.flush()
            return existing, False
        billing_code = BillingCode(exchange_id=exchange_id, code=code, **defaults)
        self.session.add(billing_code)
        await self.session.flush()
        return billing_code, True
