"""Canonical fee schema - Pydantic models for normalized fee data."""

from datetime import date
from decimal import Decimal
from enum import Enum

from pydantic import BaseModel, Field


class ParticipantType(str, Enum):
    CUSTOMER = "CUSTOMER"
    PROFESSIONAL = "PROFESSIONAL"
    MARKET_MAKER = "MARKET_MAKER"
    AWAY_MARKET_MAKER = "AWAY_MARKET_MAKER"
    FIRM = "FIRM"
    BROKER_DEALER = "BROKER_DEALER"


class SecurityClass(str, Enum):
    PENNY = "PENNY"
    NON_PENNY = "NON_PENNY"
    INDEX = "INDEX"
    ETF = "ETF"
    EQUITY = "EQUITY"
    MINI = "MINI"


class OrderType(str, Enum):
    SIMPLE = "SIMPLE"
    COMPLEX = "COMPLEX"
    AUCTION = "AUCTION"
    DIRECTED = "DIRECTED"
    QCC = "QCC"


class FeeType(str, Enum):
    MAKER = "MAKER"
    TAKER = "TAKER"
    ROUTING = "ROUTING"
    ORF = "ORF"
    TRANSACTION = "TRANSACTION"
    CLEARING = "CLEARING"
    CONNECTIVITY = "CONNECTIVITY"
    MARKET_DATA = "MARKET_DATA"
    MEMBERSHIP = "MEMBERSHIP"


class NormalizedFeeEntry(BaseModel):
    """A single normalized fee entry."""

    exchange_code: str
    participant_type: ParticipantType
    security_class: SecurityClass
    order_type: OrderType
    fee_type: FeeType
    amount: Decimal = Field(description="Per-contract amount in USD. Negative for rebates.")
    is_rebate: bool = False
    volume_tier: str | None = None
    tier_threshold_pct: float | None = Field(
        default=None, description="Tier threshold as % of total OCV"
    )
    tier_threshold_contracts: int | None = Field(
        default=None, description="Tier threshold in absolute contracts"
    )
    effective_date: date | None = None
    notes: str | None = None

    @property
    def amount_cents(self) -> int:
        """Amount in hundredths of a cent for database storage."""
        return int(self.amount * 10000)


class NormalizedFeeSchedule(BaseModel):
    """Complete normalized fee schedule for an exchange."""

    exchange_code: str
    exchange_name: str
    effective_date: date | None = None
    fees: list[NormalizedFeeEntry] = Field(default_factory=list)
    parsing_confidence: float = 0.0
    extraction_notes: str = ""

    @property
    def fee_count(self) -> int:
        return len(self.fees)

    def get_fees(
        self,
        participant_type: ParticipantType | None = None,
        security_class: SecurityClass | None = None,
        fee_type: FeeType | None = None,
        order_type: OrderType | None = None,
    ) -> list[NormalizedFeeEntry]:
        """Filter fees by criteria."""
        result = self.fees
        if participant_type:
            result = [f for f in result if f.participant_type == participant_type]
        if security_class:
            result = [f for f in result if f.security_class == security_class]
        if fee_type:
            result = [f for f in result if f.fee_type == fee_type]
        if order_type:
            result = [f for f in result if f.order_type == order_type]
        return result
