import enum
import uuid
from datetime import date, datetime

from sqlalchemy import (
    Boolean,
    Date,
    DateTime,
    Enum,
    Float,
    ForeignKey,
    Integer,
    LargeBinary,
    String,
    Text,
    func,
)
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column, relationship


class Base(DeclarativeBase):
    pass


# --- Enums ---


class FeeScheduleFormat(str, enum.Enum):
    PDF = "PDF"
    HTML = "HTML"
    EXCEL = "EXCEL"


class ScraperType(str, enum.Enum):
    HTTP = "HTTP"
    BROWSER = "BROWSER"


class SnapshotStatus(str, enum.Enum):
    PENDING = "PENDING"
    PARSED = "PARSED"
    NORMALIZED = "NORMALIZED"
    VERIFIED = "VERIFIED"
    FAILED = "FAILED"


class ParticipantType(str, enum.Enum):
    CUSTOMER = "CUSTOMER"
    PROFESSIONAL = "PROFESSIONAL"
    MARKET_MAKER = "MARKET_MAKER"
    AWAY_MARKET_MAKER = "AWAY_MARKET_MAKER"
    FIRM = "FIRM"
    BROKER_DEALER = "BROKER_DEALER"


class SecurityClass(str, enum.Enum):
    PENNY = "PENNY"
    NON_PENNY = "NON_PENNY"
    INDEX = "INDEX"
    ETF = "ETF"
    EQUITY = "EQUITY"
    MINI = "MINI"


class OrderType(str, enum.Enum):
    SIMPLE = "SIMPLE"
    COMPLEX = "COMPLEX"
    AUCTION = "AUCTION"
    DIRECTED = "DIRECTED"
    QCC = "QCC"


class FeeType(str, enum.Enum):
    MAKER = "MAKER"
    TAKER = "TAKER"
    ROUTING = "ROUTING"
    ORF = "ORF"
    TRANSACTION = "TRANSACTION"
    CLEARING = "CLEARING"
    CONNECTIVITY = "CONNECTIVITY"
    MARKET_DATA = "MARKET_DATA"
    MEMBERSHIP = "MEMBERSHIP"


class ChangeType(str, enum.Enum):
    NEW = "NEW"
    MODIFIED = "MODIFIED"
    REMOVED = "REMOVED"


class NotificationFrequency(str, enum.Enum):
    IMMEDIATE = "IMMEDIATE"
    DAILY_DIGEST = "DAILY_DIGEST"
    WEEKLY = "WEEKLY"


class DeliveryStatus(str, enum.Enum):
    SENT = "SENT"
    FAILED = "FAILED"
    BOUNCED = "BOUNCED"


class ScrapeStatus(str, enum.Enum):
    SUCCESS = "SUCCESS"
    FAILED = "FAILED"
    NO_CHANGE = "NO_CHANGE"


# --- Models ---


class Exchange(Base):
    __tablename__ = "exchanges"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    code: Mapped[str] = mapped_column(String(50), unique=True, nullable=False, index=True)
    name: Mapped[str] = mapped_column(String(200), nullable=False)
    operator: Mapped[str] = mapped_column(String(200), nullable=False)
    fee_schedule_url: Mapped[str] = mapped_column(String(500), nullable=False)
    alternate_urls: Mapped[dict | None] = mapped_column(JSONB, nullable=True)
    fee_schedule_format: Mapped[FeeScheduleFormat] = mapped_column(
        Enum(FeeScheduleFormat), nullable=False
    )
    scraper_type: Mapped[ScraperType] = mapped_column(Enum(ScraperType), nullable=False)
    parser_hints: Mapped[dict | None] = mapped_column(JSONB, nullable=True)
    is_active: Mapped[bool] = mapped_column(Boolean, default=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(
        DateTime, server_default=func.now(), onupdate=func.now()
    )

    snapshots: Mapped[list["FeeScheduleSnapshot"]] = relationship(back_populates="exchange")
    normalized_fees: Mapped[list["NormalizedFee"]] = relationship(back_populates="exchange")
    fee_changes: Mapped[list["FeeChange"]] = relationship(back_populates="exchange")
    scrape_logs: Mapped[list["ScrapeLog"]] = relationship(back_populates="exchange")


class FeeScheduleSnapshot(Base):
    __tablename__ = "fee_schedule_snapshots"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    exchange_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("exchanges.id"), nullable=False, index=True
    )
    version: Mapped[int] = mapped_column(Integer, nullable=False)
    effective_date: Mapped[date | None] = mapped_column(Date, nullable=True)
    source_url: Mapped[str] = mapped_column(String(500), nullable=False)
    source_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    raw_document: Mapped[bytes | None] = mapped_column(LargeBinary, nullable=True)
    raw_text: Mapped[str | None] = mapped_column(Text, nullable=True)
    ai_extraction: Mapped[dict | None] = mapped_column(JSONB, nullable=True)
    normalized_fees_json: Mapped[dict | None] = mapped_column(JSONB, nullable=True)
    parsing_confidence: Mapped[float | None] = mapped_column(Float, nullable=True)
    status: Mapped[SnapshotStatus] = mapped_column(
        Enum(SnapshotStatus), default=SnapshotStatus.PENDING
    )
    error_log: Mapped[str | None] = mapped_column(Text, nullable=True)
    milestone_tag: Mapped[str | None] = mapped_column(String(100), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now())

    exchange: Mapped["Exchange"] = relationship(back_populates="snapshots")
    normalized_fees: Mapped[list["NormalizedFee"]] = relationship(back_populates="snapshot")


class NormalizedFee(Base):
    __tablename__ = "normalized_fees"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    snapshot_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("fee_schedule_snapshots.id"), nullable=False, index=True
    )
    exchange_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("exchanges.id"), nullable=False, index=True
    )
    participant_type: Mapped[ParticipantType] = mapped_column(
        Enum(ParticipantType), nullable=False
    )
    security_class: Mapped[SecurityClass] = mapped_column(Enum(SecurityClass), nullable=False)
    order_type: Mapped[OrderType] = mapped_column(Enum(OrderType), nullable=False)
    fee_type: Mapped[FeeType] = mapped_column(Enum(FeeType), nullable=False)
    amount_cents: Mapped[int] = mapped_column(
        Integer, nullable=False, comment="Fee in hundredths of a cent for precision"
    )
    is_rebate: Mapped[bool] = mapped_column(Boolean, default=False)
    volume_tier: Mapped[str | None] = mapped_column(String(100), nullable=True)
    tier_threshold_pct: Mapped[float | None] = mapped_column(Float, nullable=True)
    tier_threshold_contracts: Mapped[int | None] = mapped_column(Integer, nullable=True)
    effective_date: Mapped[date | None] = mapped_column(Date, nullable=True)
    notes: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now())

    snapshot: Mapped["FeeScheduleSnapshot"] = relationship(back_populates="normalized_fees")
    exchange: Mapped["Exchange"] = relationship(back_populates="normalized_fees")


class FeeChange(Base):
    __tablename__ = "fee_changes"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    exchange_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("exchanges.id"), nullable=False, index=True
    )
    old_snapshot_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("fee_schedule_snapshots.id"), nullable=True
    )
    new_snapshot_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("fee_schedule_snapshots.id"), nullable=False
    )
    change_type: Mapped[ChangeType] = mapped_column(Enum(ChangeType), nullable=False)
    participant_type: Mapped[ParticipantType | None] = mapped_column(
        Enum(ParticipantType), nullable=True
    )
    security_class: Mapped[SecurityClass | None] = mapped_column(
        Enum(SecurityClass), nullable=True
    )
    order_type: Mapped[OrderType | None] = mapped_column(Enum(OrderType), nullable=True)
    fee_type: Mapped[FeeType | None] = mapped_column(Enum(FeeType), nullable=True)
    old_amount_cents: Mapped[int | None] = mapped_column(Integer, nullable=True)
    new_amount_cents: Mapped[int | None] = mapped_column(Integer, nullable=True)
    change_description: Mapped[str | None] = mapped_column(Text, nullable=True)
    detected_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now())
    notified: Mapped[bool] = mapped_column(Boolean, default=False)

    exchange: Mapped["Exchange"] = relationship(back_populates="fee_changes")
    old_snapshot: Mapped["FeeScheduleSnapshot | None"] = relationship(
        foreign_keys=[old_snapshot_id]
    )
    new_snapshot: Mapped["FeeScheduleSnapshot"] = relationship(foreign_keys=[new_snapshot_id])


class User(Base):
    __tablename__ = "users"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    email: Mapped[str] = mapped_column(String(255), unique=True, nullable=False, index=True)
    username: Mapped[str] = mapped_column(String(100), unique=True, nullable=False)
    hashed_password: Mapped[str] = mapped_column(String(255), nullable=False)
    is_active: Mapped[bool] = mapped_column(Boolean, default=True)
    is_admin: Mapped[bool] = mapped_column(Boolean, default=False)
    created_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now())


class Subscriber(Base):
    __tablename__ = "subscribers"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    email: Mapped[str] = mapped_column(String(255), unique=True, nullable=False, index=True)
    name: Mapped[str | None] = mapped_column(String(200), nullable=True)
    is_active: Mapped[bool] = mapped_column(Boolean, default=True)
    exchanges_filter: Mapped[dict | None] = mapped_column(
        JSONB, nullable=True, comment="null = all exchanges, or list of exchange codes"
    )
    notification_frequency: Mapped[NotificationFrequency] = mapped_column(
        Enum(NotificationFrequency), default=NotificationFrequency.DAILY_DIGEST
    )
    created_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now())


class NotificationLog(Base):
    __tablename__ = "notification_logs"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    subscriber_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("subscribers.id"), nullable=False
    )
    fee_change_ids: Mapped[dict | None] = mapped_column(JSONB, nullable=True)
    email_subject: Mapped[str] = mapped_column(String(500), nullable=False)
    sent_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now())
    delivery_status: Mapped[DeliveryStatus] = mapped_column(
        Enum(DeliveryStatus), default=DeliveryStatus.SENT
    )

    subscriber: Mapped["Subscriber"] = relationship()


class ScrapeLog(Base):
    __tablename__ = "scrape_logs"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    exchange_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("exchanges.id"), nullable=False, index=True
    )
    started_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now())
    completed_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    status: Mapped[ScrapeStatus] = mapped_column(Enum(ScrapeStatus), nullable=False)
    document_hash: Mapped[str | None] = mapped_column(String(64), nullable=True)
    has_changes: Mapped[bool] = mapped_column(Boolean, default=False)
    error_message: Mapped[str | None] = mapped_column(Text, nullable=True)

    exchange: Mapped["Exchange"] = relationship(back_populates="scrape_logs")
