"""API request/response Pydantic schemas."""

import uuid
from datetime import date, datetime
from decimal import Decimal

from pydantic import BaseModel, EmailStr, Field

# --- Exchange schemas ---


class ExchangeResponse(BaseModel):
    id: uuid.UUID
    code: str
    name: str
    operator: str
    fee_schedule_url: str
    fee_schedule_format: str
    is_active: bool
    latest_version: int | None = None
    latest_snapshot_date: datetime | None = None

    model_config = {"from_attributes": True}


class ExchangeListResponse(BaseModel):
    data: list[ExchangeResponse]
    count: int


# --- Fee schemas ---


class NormalizedFeeResponse(BaseModel):
    id: uuid.UUID
    exchange_code: str
    participant_type: str
    security_class: str
    order_type: str
    fee_type: str
    amount: Decimal
    is_rebate: bool
    volume_tier: str | None = None
    tier_threshold_pct: float | None = None
    tier_threshold_contracts: int | None = None
    effective_date: date | None = None
    notes: str | None = None

    model_config = {"from_attributes": True}

    @classmethod
    def from_db_model(cls, fee) -> "NormalizedFeeResponse":
        return cls(
            id=fee.id,
            exchange_code=fee.exchange.code if fee.exchange else "",
            participant_type=fee.participant_type.value,
            security_class=fee.security_class.value,
            order_type=fee.order_type.value,
            fee_type=fee.fee_type.value,
            amount=Decimal(fee.amount_cents) / Decimal(10000),
            is_rebate=fee.is_rebate,
            volume_tier=fee.volume_tier,
            tier_threshold_pct=fee.tier_threshold_pct,
            tier_threshold_contracts=fee.tier_threshold_contracts,
            effective_date=fee.effective_date,
            notes=fee.notes,
        )


class FeeListResponse(BaseModel):
    data: list[NormalizedFeeResponse]
    exchange_code: str
    version: int | None = None
    count: int


# --- Snapshot schemas ---


class SnapshotResponse(BaseModel):
    id: uuid.UUID
    exchange_code: str
    version: int
    effective_date: date | None = None
    source_url: str
    source_hash: str
    parsing_confidence: float | None = None
    status: str
    milestone_tag: str | None = None
    created_at: datetime
    fee_count: int = 0

    model_config = {"from_attributes": True}


class SnapshotHistoryResponse(BaseModel):
    data: list[SnapshotResponse]
    exchange_code: str
    count: int


# --- Change schemas ---


class FeeChangeResponse(BaseModel):
    id: uuid.UUID
    exchange_code: str
    change_type: str
    participant_type: str | None = None
    security_class: str | None = None
    order_type: str | None = None
    fee_type: str | None = None
    old_amount: Decimal | None = None
    new_amount: Decimal | None = None
    change_description: str | None = None
    detected_at: datetime

    model_config = {"from_attributes": True}

    @classmethod
    def from_db_model(cls, change) -> "FeeChangeResponse":
        return cls(
            id=change.id,
            exchange_code=change.exchange.code if change.exchange else "",
            change_type=change.change_type.value,
            participant_type=change.participant_type.value if change.participant_type else None,
            security_class=change.security_class.value if change.security_class else None,
            order_type=change.order_type.value if change.order_type else None,
            fee_type=change.fee_type.value if change.fee_type else None,
            old_amount=Decimal(change.old_amount_cents) / Decimal(10000) if change.old_amount_cents is not None else None,
            new_amount=Decimal(change.new_amount_cents) / Decimal(10000) if change.new_amount_cents is not None else None,
            change_description=change.change_description,
            detected_at=change.detected_at,
        )


class RecentChangesResponse(BaseModel):
    data: list[FeeChangeResponse]
    count: int


# --- Comparison schemas ---


class ComparisonCellResponse(BaseModel):
    exchange_code: str
    amount: Decimal
    is_rebate: bool
    volume_tier: str | None = None


class ComparisonRowResponse(BaseModel):
    participant_type: str
    security_class: str
    order_type: str
    fee_type: str
    exchanges: dict[str, ComparisonCellResponse]
    cheapest: str | None = None
    most_expensive: str | None = None


class ComparisonResponse(BaseModel):
    exchange_codes: list[str]
    rows: list[ComparisonRowResponse]
    filters: dict


# --- Subscriber schemas ---


class SubscriberCreate(BaseModel):
    email: EmailStr
    name: str | None = None
    exchanges_filter: list[str] | None = Field(
        default=None, description="List of exchange codes to monitor. Null for all."
    )
    notification_frequency: str = "DAILY_DIGEST"


class SubscriberResponse(BaseModel):
    id: uuid.UUID
    email: str
    name: str | None = None
    is_active: bool
    exchanges_filter: list[str] | None = None
    notification_frequency: str
    created_at: datetime

    model_config = {"from_attributes": True}


# --- Auth schemas ---


class LoginRequest(BaseModel):
    username: str
    password: str


class TokenResponse(BaseModel):
    access_token: str
    token_type: str = "bearer"


class UserResponse(BaseModel):
    id: uuid.UUID
    email: str
    username: str
    is_admin: bool

    model_config = {"from_attributes": True}


# --- Admin schemas ---


class ScrapedDocumentResponse(BaseModel):
    id: uuid.UUID
    snapshot_id: uuid.UUID
    content_type: str
    source_url: str
    content_hash: str
    storage_path: str
    file_size_bytes: int
    is_primary: bool
    fetched_at: datetime

    model_config = {"from_attributes": True}


class ScrapeLogResponse(BaseModel):
    id: uuid.UUID
    exchange_code: str
    started_at: datetime
    completed_at: datetime | None = None
    status: str
    document_hash: str | None = None
    has_changes: bool
    error_message: str | None = None

    model_config = {"from_attributes": True}


class ScrapeResponse(BaseModel):
    message: str
    task_id: str | None = None
