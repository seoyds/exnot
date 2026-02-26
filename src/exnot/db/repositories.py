import uuid
from datetime import datetime

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from exnot.db.models import (
    Exchange,
    FeeChange,
    FeeScheduleSnapshot,
    NormalizedFee,
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

    async def get_history(
        self, exchange_id: uuid.UUID, limit: int = 50
    ) -> list[FeeScheduleSnapshot]:
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

    async def get_for_exchange(
        self, exchange_id: uuid.UUID, limit: int = 50
    ) -> list[FeeChange]:
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
