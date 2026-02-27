"""Fee normalization engine - converts AI-extracted raw fees into canonical schema."""

import logging
from datetime import date, datetime
from decimal import Decimal, InvalidOperation

from exnot.normalizer.schema import (
    FeeType,
    FeeUnit,
    NormalizedFeeEntry,
    NormalizedFeeSchedule,
    OrderType,
    ParticipantType,
    SecurityClass,
    TierCondition,
    TierConditionCriterion,
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
    "cmm": ParticipantType.MARKET_MAKER,
    "away market maker": ParticipantType.AWAY_MARKET_MAKER,
    "non-member market maker": ParticipantType.AWAY_MARKET_MAKER,
    "remote market maker": ParticipantType.AWAY_MARKET_MAKER,
    "farmm": ParticipantType.AWAY_MARKET_MAKER,
    "non-nasdaq ise market maker": ParticipantType.AWAY_MARKET_MAKER,
    "firm": ParticipantType.FIRM,
    "proprietary": ParticipantType.FIRM,
    "broker-dealer": ParticipantType.BROKER_DEALER,
    "broker dealer": ParticipantType.BROKER_DEALER,
    "bd": ParticipantType.BROKER_DEALER,
    "jbo": ParticipantType.BROKER_DEALER,
    "non-customer": ParticipantType.NON_CUSTOMER,
    "non customer": ParticipantType.NON_CUSTOMER,
    "all": ParticipantType.ALL,
}

SECURITY_MAPPINGS: dict[str, SecurityClass] = {
    "penny": SecurityClass.PENNY,
    "penny pilot": SecurityClass.PENNY,
    "penny classes": SecurityClass.PENNY,
    "select symbols": SecurityClass.PENNY,
    "non-penny": SecurityClass.NON_PENNY,
    "non penny": SecurityClass.NON_PENNY,
    "non-penny pilot": SecurityClass.NON_PENNY,
    "non-select symbols": SecurityClass.NON_PENNY,
    "index": SecurityClass.INDEX,
    "index options": SecurityClass.INDEX,
    "spx": SecurityClass.INDEX,
    "etf": SecurityClass.ETF,
    "etf options": SecurityClass.ETF,
    "equity": SecurityClass.EQUITY,
    "equity options": SecurityClass.EQUITY,
    "mini": SecurityClass.MINI,
    "mini options": SecurityClass.MINI,
    "spy": SecurityClass.SPY,
    "qqq": SecurityClass.QQQ,
    "iwm": SecurityClass.IWM,
    "ndx": SecurityClass.NDX,
    "rut": SecurityClass.RUT,
    "vix": SecurityClass.VIX,
    "all": SecurityClass.ALL,
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
    "directed": OrderType.DIRECTED,
    "qcc": OrderType.QCC,
    "qualified contingent cross": OrderType.QCC,
    "pim": OrderType.PIM,
    "prime": OrderType.PIM,
    "cprime": OrderType.PIM,
    "price improvement": OrderType.PIM,
    "pip": OrderType.PIM,
    "crossing": OrderType.CROSSING,
    "solicitation": OrderType.CROSSING,
    "fac": OrderType.CROSSING,
    "flex": OrderType.FLEX,
    "opening": OrderType.OPENING,
    "routed": OrderType.ROUTED,
    "routing": OrderType.ROUTED,
    "all": OrderType.ALL,
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
    "crossing fee": FeeType.CROSSING_FEE,
    "crossing": FeeType.CROSSING_FEE,
    "pim fee": FeeType.PIM_FEE,
    "pim": FeeType.PIM_FEE,
    "response fee": FeeType.RESPONSE_FEE,
    "response": FeeType.RESPONSE_FEE,
    "break up rebate": FeeType.BREAK_UP_REBATE,
    "break-up rebate": FeeType.BREAK_UP_REBATE,
    "breakup": FeeType.BREAK_UP_REBATE,
    "surcharge": FeeType.SURCHARGE,
    "index surcharge": FeeType.SURCHARGE,
    "license surcharge": FeeType.SURCHARGE,
    "cancellation": FeeType.CANCELLATION,
    "cancel": FeeType.CANCELLATION,
    "stock handling": FeeType.STOCK_HANDLING,
    "stock leg": FeeType.STOCK_HANDLING,
}

FEE_UNIT_MAPPINGS: dict[str, FeeUnit] = {
    "per_contract": FeeUnit.PER_CONTRACT,
    "per contract": FeeUnit.PER_CONTRACT,
    "per_contract_side": FeeUnit.PER_CONTRACT_SIDE,
    "per contract side": FeeUnit.PER_CONTRACT_SIDE,
    "per_share": FeeUnit.PER_SHARE,
    "per share": FeeUnit.PER_SHARE,
    "monthly_flat": FeeUnit.MONTHLY_FLAT,
    "monthly flat": FeeUnit.MONTHLY_FLAT,
    "per_port_monthly": FeeUnit.PER_PORT_MONTHLY,
    "per port monthly": FeeUnit.PER_PORT_MONTHLY,
    "percentage": FeeUnit.PERCENTAGE,
    "percent": FeeUnit.PERCENTAGE,
    "per_order": FeeUnit.PER_ORDER,
    "per order": FeeUnit.PER_ORDER,
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
            effective_date = self._parse_date(extraction.effective_date)

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
            logger.warning(
                f"Skipping fee with unmappable type: "
                f"participant={raw.get('participant_type')!r} -> {participant_type}, "
                f"fee_type={raw.get('fee_type')!r} -> {fee_type}"
            )
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

        # V2 fields
        contra_party_type = self._map_participant(raw.get("contra_party_type") or "")
        fee_unit = self._map_fee_unit(raw.get("fee_unit", ""))
        tier_conditions = self._parse_tier_conditions(raw.get("tier_conditions"))

        return NormalizedFeeEntry(
            exchange_code=exchange_code,
            fee_code=raw.get("fee_code"),
            participant_type=participant_type,
            contra_party_type=contra_party_type,
            security_class=security_class or SecurityClass.EQUITY,
            symbol=raw.get("symbol"),
            order_type=order_type or OrderType.SIMPLE,
            fee_type=fee_type,
            fee_unit=fee_unit or FeeUnit.PER_CONTRACT,
            amount=amount,
            is_rebate=is_rebate,
            routing_destination=raw.get("routing_destination"),
            tier_group=raw.get("tier_group"),
            tier_number=raw.get("tier_number"),
            tier_conditions=tier_conditions,
            conditions=raw.get("conditions"),
            effective_date=self._parse_date(raw.get("effective_date") or ""),
            expiry_date=self._parse_date(raw.get("expiry_date") or ""),
            section_ref=raw.get("section_ref"),
            notes=raw.get("notes"),
            # Legacy fields (backward compatibility)
            volume_tier=raw.get("volume_tier"),
            tier_threshold_pct=raw.get("tier_threshold_pct"),
            tier_threshold_contracts=raw.get("tier_threshold_contracts"),
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

    def _map_fee_unit(self, value: str) -> FeeUnit | None:
        if not value:
            return None
        try:
            return FeeUnit(value.upper())
        except ValueError:
            pass
        key = value.lower().strip()
        return FEE_UNIT_MAPPINGS.get(key)

    def _parse_tier_conditions(self, raw: dict | None) -> TierCondition | None:
        """Parse a raw tier_conditions dict into a TierCondition model."""
        if not raw or not isinstance(raw, dict):
            return None
        try:
            criteria = []
            for c in raw.get("criteria", []):
                criteria.append(TierConditionCriterion(
                    metric=c.get("metric", ""),
                    capacities=c.get("capacities"),
                    security_filter=c.get("security_filter"),
                    operator=c.get("operator", ">="),
                    value=float(c.get("value", 0)),
                    unit=c.get("unit", ""),
                    description=c.get("description", ""),
                ))
            return TierCondition(
                logic=raw.get("logic", "AND"),
                criteria=criteria,
            )
        except Exception as e:
            logger.warning(f"Failed to parse tier_conditions: {e}")
            return None

    @staticmethod
    def _parse_date(date_str: str) -> date | None:
        """Parse dates in various formats (ISO, natural language, etc.)."""
        if not date_str:
            return None
        # Try ISO format first
        try:
            return date.fromisoformat(date_str)
        except (ValueError, TypeError):
            pass
        # Try common natural language formats
        for fmt in ("%B %d, %Y", "%b %d, %Y", "%m/%d/%Y", "%d %B %Y"):
            try:
                return datetime.strptime(date_str, fmt).date()
            except (ValueError, TypeError):
                continue
        logger.warning(f"Could not parse effective date: {date_str}")
        return None
