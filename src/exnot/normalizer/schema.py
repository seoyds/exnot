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
    NON_CUSTOMER = "NON_CUSTOMER"
    ALL = "ALL"


class SecurityClass(str, Enum):
    PENNY = "PENNY"
    NON_PENNY = "NON_PENNY"
    INDEX = "INDEX"
    ETF = "ETF"
    EQUITY = "EQUITY"
    MINI = "MINI"
    SPY = "SPY"
    QQQ = "QQQ"
    IWM = "IWM"
    NDX = "NDX"
    RUT = "RUT"
    VIX = "VIX"
    ALL = "ALL"


class OrderType(str, Enum):
    SIMPLE = "SIMPLE"
    COMPLEX = "COMPLEX"
    AUCTION = "AUCTION"
    DIRECTED = "DIRECTED"
    QCC = "QCC"
    PIM = "PIM"
    CROSSING = "CROSSING"
    FLEX = "FLEX"
    OPENING = "OPENING"
    ROUTED = "ROUTED"
    ALL = "ALL"


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
    CROSSING_FEE = "CROSSING_FEE"
    PIM_FEE = "PIM_FEE"
    RESPONSE_FEE = "RESPONSE_FEE"
    BREAK_UP_REBATE = "BREAK_UP_REBATE"
    SURCHARGE = "SURCHARGE"
    CANCELLATION = "CANCELLATION"
    STOCK_HANDLING = "STOCK_HANDLING"


class FeeUnit(str, Enum):
    PER_CONTRACT = "PER_CONTRACT"
    PER_CONTRACT_SIDE = "PER_CONTRACT_SIDE"
    PER_SHARE = "PER_SHARE"
    MONTHLY_FLAT = "MONTHLY_FLAT"
    PER_PORT_MONTHLY = "PER_PORT_MONTHLY"
    PERCENTAGE = "PERCENTAGE"
    PER_ORDER = "PER_ORDER"


class OriginCode(str, Enum):
    CUSTOMER = "CUSTOMER"
    PROFESSIONAL = "PROFESSIONAL"
    FIRM = "FIRM"
    BROKER_DEALER = "BROKER_DEALER"
    MARKET_MAKER = "MARKET_MAKER"
    AWAY_MARKET_MAKER = "AWAY_MARKET_MAKER"
    ANY = "ANY"


class ProductType(str, Enum):
    SIMPLE = "SIMPLE"
    COMPLEX = "COMPLEX"


class ListingType(str, Enum):
    EQUITY = "EQUITY"
    ETF = "ETF"
    INDEX = "INDEX"


class PennyClass(str, Enum):
    PENNY = "PENNY"
    NON_PENNY = "NON_PENNY"


class ExecVenue(str, Enum):
    ELECTRONIC = "ELECTRONIC"
    FLOOR = "FLOOR"
    ROUTED = "ROUTED"


class LiquidityRole(str, Enum):
    MAKER = "MAKER"
    TAKER = "TAKER"
    NONE = "NONE"


class TierConditionCriterion(BaseModel):
    """A single criterion within a tier condition."""

    metric: str = Field(description="ADAV, ADRV, ADV, NBBO_PCT, TOTAL_VOLUME, CCV_PCT, CROSS_ASSET")
    capacities: list[str] | None = Field(default=None, description="Participant types counted")
    security_filter: str | None = None
    operator: str = Field(description=">=, <=, >, <, ==")
    value: float = Field(description="Threshold value")
    unit: str = Field(description="PCT_OCV, PCT_CCV, PCT_TCV, CONTRACTS, PERCENT")
    description: str = ""


class TierCondition(BaseModel):
    """Structured tier condition with AND/OR logic."""

    logic: str = Field(default="AND", description="AND or OR")
    criteria: list[TierConditionCriterion] = Field(default_factory=list)


class NormalizedFeeEntry(BaseModel):
    """A single normalized fee entry."""

    exchange_code: str
    fee_code: str | None = None
    participant_type: ParticipantType
    contra_party_type: ParticipantType | None = None
    security_class: SecurityClass
    symbol: str | None = None
    order_type: OrderType
    fee_type: FeeType
    fee_unit: FeeUnit = FeeUnit.PER_CONTRACT
    amount: Decimal = Field(description="Per-contract amount in USD. Negative for rebates.")
    is_rebate: bool = False
    routing_destination: str | None = None
    tier_group: str | None = None
    tier_number: int | None = None
    tier_conditions: TierCondition | None = None
    conditions: dict | None = None
    effective_date: date | None = None
    expiry_date: date | None = None
    section_ref: str | None = None
    notes: str | None = None

    # Kept for backward compatibility
    volume_tier: str | None = None
    tier_threshold_pct: float | None = None
    tier_threshold_contracts: int | None = None

    # V3 dimensions (preserved for DB storage)
    origin_code: str | None = None
    contra_origin_code: str | None = None
    product_type_v3: str | None = None
    listing_type: str | None = None
    penny_class: str | None = None
    multi_listed: bool | None = None
    exec_venue: str | None = None
    liquidity_role: str | None = None
    auction_type: str | None = None
    auction_role: str | None = None
    fee_name: str | None = None
    tier_level: int | None = None
    tier_condition_text: str | None = None

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
    tiers: list[dict] = Field(default_factory=list, description="Tier group definitions")
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
