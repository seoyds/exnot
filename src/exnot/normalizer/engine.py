"""Fee normalization engine - converts AI-extracted raw fees into canonical schema."""

import logging
from datetime import date
from decimal import Decimal, InvalidOperation

from exnot.normalizer.schema import (
    FeeType,
    NormalizedFeeEntry,
    NormalizedFeeSchedule,
    OrderType,
    ParticipantType,
    SecurityClass,
)
from exnot.parser.ai_extractor import ExtractionResult

logger = logging.getLogger(__name__)

# Mapping from exchange-specific terminology to canonical types
PARTICIPANT_MAPPINGS: dict[str, ParticipantType] = {
    "customer": ParticipantType.CUSTOMER,
    "public customer": ParticipantType.CUSTOMER,
    "priority customer": ParticipantType.CUSTOMER,
    "retail": ParticipantType.CUSTOMER,
    "retail customer": ParticipantType.CUSTOMER,
    "professional": ParticipantType.PROFESSIONAL,
    "professional customer": ParticipantType.PROFESSIONAL,
    "market maker": ParticipantType.MARKET_MAKER,
    "specialist": ParticipantType.MARKET_MAKER,
    "lead market maker": ParticipantType.MARKET_MAKER,
    "lmm": ParticipantType.MARKET_MAKER,
    "dpm": ParticipantType.MARKET_MAKER,
    "pmm": ParticipantType.MARKET_MAKER,
    "primary market maker": ParticipantType.MARKET_MAKER,
    "competitive market maker": ParticipantType.MARKET_MAKER,
    "away market maker": ParticipantType.AWAY_MARKET_MAKER,
    "non-member market maker": ParticipantType.AWAY_MARKET_MAKER,
    "remote market maker": ParticipantType.AWAY_MARKET_MAKER,
    "firm": ParticipantType.FIRM,
    "proprietary": ParticipantType.FIRM,
    "non-customer": ParticipantType.FIRM,
    "non customer": ParticipantType.FIRM,
    "broker-dealer": ParticipantType.BROKER_DEALER,
    "broker dealer": ParticipantType.BROKER_DEALER,
    "bd": ParticipantType.BROKER_DEALER,
}

SECURITY_MAPPINGS: dict[str, SecurityClass] = {
    "penny": SecurityClass.PENNY,
    "penny pilot": SecurityClass.PENNY,
    "penny classes": SecurityClass.PENNY,
    "non-penny": SecurityClass.NON_PENNY,
    "non penny": SecurityClass.NON_PENNY,
    "non-penny pilot": SecurityClass.NON_PENNY,
    "index": SecurityClass.INDEX,
    "index options": SecurityClass.INDEX,
    "spx": SecurityClass.INDEX,
    "vix": SecurityClass.INDEX,
    "etf": SecurityClass.ETF,
    "etf options": SecurityClass.ETF,
    "equity": SecurityClass.EQUITY,
    "equity options": SecurityClass.EQUITY,
    "mini": SecurityClass.MINI,
    "mini options": SecurityClass.MINI,
}

ORDER_MAPPINGS: dict[str, OrderType] = {
    "simple": OrderType.SIMPLE,
    "standard": OrderType.SIMPLE,
    "regular": OrderType.SIMPLE,
    "complex": OrderType.COMPLEX,
    "multi-leg": OrderType.COMPLEX,
    "multi leg": OrderType.COMPLEX,
    "spread": OrderType.COMPLEX,
    "auction": OrderType.AUCTION,
    "aim": OrderType.AUCTION,
    "pip": OrderType.AUCTION,
    "price improvement": OrderType.AUCTION,
    "directed": OrderType.DIRECTED,
    "qcc": OrderType.QCC,
    "qualified contingent cross": OrderType.QCC,
}

FEE_TYPE_MAPPINGS: dict[str, FeeType] = {
    "maker": FeeType.MAKER,
    "add": FeeType.MAKER,
    "add liquidity": FeeType.MAKER,
    "taker": FeeType.TAKER,
    "remove": FeeType.TAKER,
    "remove liquidity": FeeType.TAKER,
    "routing": FeeType.ROUTING,
    "route": FeeType.ROUTING,
    "orf": FeeType.ORF,
    "options regulatory fee": FeeType.ORF,
    "regulatory": FeeType.ORF,
    "transaction": FeeType.TRANSACTION,
    "section 31": FeeType.TRANSACTION,
    "taf": FeeType.TRANSACTION,
    "clearing": FeeType.CLEARING,
    "comparison": FeeType.CLEARING,
    "connectivity": FeeType.CONNECTIVITY,
    "port": FeeType.CONNECTIVITY,
    "market data": FeeType.MARKET_DATA,
    "data": FeeType.MARKET_DATA,
    "membership": FeeType.MEMBERSHIP,
    "permit": FeeType.MEMBERSHIP,
    "access": FeeType.MEMBERSHIP,
}


class NormalizationEngine:
    """Converts AI-extracted raw fee data into canonical NormalizedFeeSchedule."""

    def normalize(self, extraction: ExtractionResult, exchange_code: str) -> NormalizedFeeSchedule:
        """Normalize raw extraction result into canonical schema."""
        fees: list[NormalizedFeeEntry] = []

        for raw_fee in extraction.raw_fees:
            try:
                entry = self._normalize_entry(raw_fee, exchange_code)
                if entry:
                    fees.append(entry)
            except Exception as e:
                logger.warning(f"Failed to normalize fee entry for {exchange_code}: {e} | {raw_fee}")

        # Parse effective date
        effective_date = None
        if extraction.effective_date:
            try:
                effective_date = date.fromisoformat(extraction.effective_date)
            except (ValueError, TypeError):
                logger.warning(f"Could not parse effective date: {extraction.effective_date}")

        schedule = NormalizedFeeSchedule(
            exchange_code=exchange_code,
            exchange_name=extraction.exchange_name or exchange_code,
            effective_date=effective_date,
            fees=fees,
            parsing_confidence=extraction.confidence,
            extraction_notes=extraction.extraction_notes,
        )

        logger.info(
            f"Normalized {len(fees)} fees for {exchange_code} "
            f"(from {len(extraction.raw_fees)} raw entries)"
        )
        return schedule

    def _normalize_entry(self, raw: dict, exchange_code: str) -> NormalizedFeeEntry | None:
        """Normalize a single raw fee entry."""
        participant_type = self._map_participant(raw.get("participant_type", ""))
        security_class = self._map_security(raw.get("security_class", ""))
        order_type = self._map_order(raw.get("order_type", ""))
        fee_type = self._map_fee_type(raw.get("fee_type", ""))

        if not participant_type or not fee_type:
            logger.debug(f"Skipping fee with unmappable type: {raw}")
            return None

        # Parse amount
        try:
            amount = Decimal(str(raw.get("amount", 0)))
        except (InvalidOperation, TypeError):
            logger.warning(f"Invalid amount in fee entry: {raw.get('amount')}")
            return None

        is_rebate = raw.get("is_rebate", False)
        if is_rebate and amount > 0:
            amount = -amount
        elif not is_rebate and amount < 0:
            is_rebate = True

        return NormalizedFeeEntry(
            exchange_code=exchange_code,
            participant_type=participant_type,
            security_class=security_class or SecurityClass.EQUITY,
            order_type=order_type or OrderType.SIMPLE,
            fee_type=fee_type,
            amount=amount,
            is_rebate=is_rebate,
            volume_tier=raw.get("volume_tier"),
            notes=raw.get("notes"),
        )

    def _map_participant(self, value: str) -> ParticipantType | None:
        if not value:
            return None
        # Try exact enum match first
        try:
            return ParticipantType(value.upper())
        except ValueError:
            pass
        # Try fuzzy mapping
        key = value.lower().strip()
        return PARTICIPANT_MAPPINGS.get(key)

    def _map_security(self, value: str) -> SecurityClass | None:
        if not value:
            return None
        try:
            return SecurityClass(value.upper())
        except ValueError:
            pass
        key = value.lower().strip()
        return SECURITY_MAPPINGS.get(key)

    def _map_order(self, value: str) -> OrderType | None:
        if not value:
            return None
        try:
            return OrderType(value.upper())
        except ValueError:
            pass
        key = value.lower().strip()
        return ORDER_MAPPINGS.get(key)

    def _map_fee_type(self, value: str) -> FeeType | None:
        if not value:
            return None
        try:
            return FeeType(value.upper())
        except ValueError:
            pass
        key = value.lower().strip()
        return FEE_TYPE_MAPPINGS.get(key)
