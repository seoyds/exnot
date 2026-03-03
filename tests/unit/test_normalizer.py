"""Tests for the normalization engine."""

from decimal import Decimal

from exnot.normalizer.engine import NormalizationEngine
from exnot.normalizer.schema import FeeType, FeeUnit, OrderType, ParticipantType, SecurityClass
from exnot.parser.ai_extractor import ExtractionResult


class TestNormalizationEngine:
    def setup_method(self):
        self.engine = NormalizationEngine()

    def test_normalize_basic_fees(self):
        extraction = ExtractionResult(
            raw_fees=[
                {
                    "participant_type": "CUSTOMER",
                    "security_class": "PENNY",
                    "order_type": "SIMPLE",
                    "fee_type": "MAKER",
                    "amount": -0.25,
                    "is_rebate": True,
                },
                {
                    "participant_type": "CUSTOMER",
                    "security_class": "PENNY",
                    "order_type": "SIMPLE",
                    "fee_type": "TAKER",
                    "amount": 0.50,
                    "is_rebate": False,
                },
            ],
            exchange_name="Test Exchange",
            confidence=0.95,
        )

        schedule = self.engine.normalize(extraction, "TEST_EX")

        assert schedule.exchange_code == "TEST_EX"
        assert len(schedule.fees) == 2
        assert schedule.fees[0].participant_type == ParticipantType.CUSTOMER
        assert schedule.fees[0].fee_type == FeeType.MAKER
        assert schedule.fees[0].amount == Decimal("-0.25")
        assert schedule.fees[0].is_rebate is True
        assert schedule.fees[1].fee_type == FeeType.TAKER
        assert schedule.fees[1].amount == Decimal("0.50")

    def test_participant_type_mapping(self):
        """Test that exchange-specific terminology maps correctly."""
        extraction = ExtractionResult(
            raw_fees=[
                {"participant_type": "Public Customer", "fee_type": "MAKER", "amount": 0.10, "is_rebate": False},
                {"participant_type": "Priority Customer", "fee_type": "MAKER", "amount": 0.10, "is_rebate": False},
                {"participant_type": "Lead Market Maker", "fee_type": "MAKER", "amount": 0.20, "is_rebate": False},
                {"participant_type": "Proprietary", "fee_type": "MAKER", "amount": 0.30, "is_rebate": False},
                {"participant_type": "Broker-Dealer", "fee_type": "MAKER", "amount": 0.35, "is_rebate": False},
            ],
            confidence=0.9,
        )

        schedule = self.engine.normalize(extraction, "TEST")

        types = [f.participant_type for f in schedule.fees]
        assert types[0] == ParticipantType.CUSTOMER  # Public Customer
        assert types[1] == ParticipantType.CUSTOMER  # Priority Customer
        assert types[2] == ParticipantType.MARKET_MAKER  # Lead Market Maker
        assert types[3] == ParticipantType.FIRM  # Proprietary
        assert types[4] == ParticipantType.BROKER_DEALER  # Broker-Dealer

    def test_rebate_normalization(self):
        """Test that rebates are correctly handled."""
        extraction = ExtractionResult(
            raw_fees=[
                # Rebate with positive amount but is_rebate=True -> should become negative
                {"participant_type": "CUSTOMER", "fee_type": "MAKER", "amount": 0.25, "is_rebate": True},
                # Fee with negative amount but is_rebate=False -> should be detected as rebate
                {"participant_type": "CUSTOMER", "fee_type": "TAKER", "amount": -0.10, "is_rebate": False},
            ],
            confidence=0.9,
        )

        schedule = self.engine.normalize(extraction, "TEST")

        assert schedule.fees[0].amount == Decimal("-0.25")
        assert schedule.fees[0].is_rebate is True
        assert schedule.fees[1].amount == Decimal("-0.10")
        assert schedule.fees[1].is_rebate is True

    def test_amount_cents_conversion(self):
        """Test amount_cents property for database storage."""
        extraction = ExtractionResult(
            raw_fees=[
                {"participant_type": "CUSTOMER", "fee_type": "TAKER", "amount": 0.4567, "is_rebate": False},
            ],
            confidence=0.9,
        )

        schedule = self.engine.normalize(extraction, "TEST")
        assert schedule.fees[0].amount_cents == 4567

    def test_empty_extraction(self):
        """Test handling of empty extraction results."""
        extraction = ExtractionResult(raw_fees=[], confidence=0.0)
        schedule = self.engine.normalize(extraction, "TEST")
        assert len(schedule.fees) == 0

    def test_invalid_amount_skipped(self):
        """Test that entries with invalid amounts are skipped."""
        extraction = ExtractionResult(
            raw_fees=[
                {"participant_type": "CUSTOMER", "fee_type": "TAKER", "amount": "invalid", "is_rebate": False},
                {"participant_type": "CUSTOMER", "fee_type": "MAKER", "amount": 0.25, "is_rebate": False},
            ],
            confidence=0.9,
        )

        schedule = self.engine.normalize(extraction, "TEST")
        assert len(schedule.fees) == 1

    def test_security_class_defaults(self):
        """Test that missing security class defaults to EQUITY."""
        extraction = ExtractionResult(
            raw_fees=[
                {"participant_type": "CUSTOMER", "fee_type": "TAKER", "amount": 0.50, "is_rebate": False},
            ],
            confidence=0.9,
        )

        schedule = self.engine.normalize(extraction, "TEST")
        assert schedule.fees[0].security_class == SecurityClass.EQUITY

    def test_v2_schema_fields(self):
        """Test that V2 schema supports new fields."""
        from exnot.normalizer.schema import NormalizedFeeEntry

        entry = NormalizedFeeEntry(
            exchange_code="CBOE_BZX",
            fee_code="ZA",
            participant_type=ParticipantType.CUSTOMER,
            contra_party_type=ParticipantType.NON_CUSTOMER,
            security_class=SecurityClass.PENNY,
            symbol=None,
            order_type="COMPLEX",
            fee_type=FeeType.MAKER,
            fee_unit=FeeUnit.PER_CONTRACT,
            amount=Decimal("-0.40"),
            is_rebate=True,
            routing_destination=None,
            tier_group="complex_customer_penny",
            tier_number=0,
            conditions={"footnotes": ["10"]},
            section_ref="Complex Orders",
        )
        assert entry.fee_code == "ZA"
        assert entry.contra_party_type == ParticipantType.NON_CUSTOMER
        assert entry.fee_unit == FeeUnit.PER_CONTRACT
        assert entry.conditions == {"footnotes": ["10"]}

    def test_v2_normalize_with_tiers(self):
        """Test V2 normalization with tier groups."""
        extraction = ExtractionResult(
            raw_fees=[
                {
                    "fee_code": "PY",
                    "participant_type": "CUSTOMER",
                    "contra_party_type": None,
                    "security_class": "PENNY",
                    "order_type": "SIMPLE",
                    "fee_type": "MAKER",
                    "fee_unit": "PER_CONTRACT",
                    "amount": -0.25,
                    "is_rebate": True,
                    "tier_group": "customer_penny_add",
                    "tier_number": 0,
                    "section_ref": "Transaction Fees",
                },
                {
                    "fee_code": "PY",
                    "participant_type": "CUSTOMER",
                    "contra_party_type": None,
                    "security_class": "PENNY",
                    "order_type": "SIMPLE",
                    "fee_type": "MAKER",
                    "fee_unit": "PER_CONTRACT",
                    "amount": -0.47,
                    "is_rebate": True,
                    "tier_group": "customer_penny_add",
                    "tier_number": 2,
                    "tier_conditions": {
                        "logic": "OR",
                        "criteria": [
                            {
                                "metric": "ADV",
                                "operator": ">=",
                                "value": 0.01,
                                "unit": "PCT_OCV",
                                "description": "ADV >= 1.00% OCV",
                            }
                        ],
                    },
                    "section_ref": "Transaction Fees, Footnote 1",
                },
                {
                    "fee_code": "ZA",
                    "participant_type": "CUSTOMER",
                    "contra_party_type": "NON_CUSTOMER",
                    "security_class": "PENNY",
                    "order_type": "COMPLEX",
                    "fee_type": "MAKER",
                    "fee_unit": "PER_CONTRACT",
                    "amount": -0.40,
                    "is_rebate": True,
                    "conditions": {"footnotes": ["10"]},
                    "section_ref": "Complex Orders",
                },
            ],
            exchange_name="Cboe BZX",
            confidence=0.95,
        )

        schedule = self.engine.normalize(extraction, "CBOE_BZX")

        assert len(schedule.fees) == 3
        # Base tier
        assert schedule.fees[0].fee_code == "PY"
        assert schedule.fees[0].tier_number == 0
        assert schedule.fees[0].tier_conditions is None
        # Volume tier
        assert schedule.fees[1].tier_number == 2
        assert schedule.fees[1].tier_conditions is not None
        assert schedule.fees[1].tier_conditions.logic == "OR"
        # Contra-party
        assert schedule.fees[2].contra_party_type == ParticipantType.NON_CUSTOMER
        assert schedule.fees[2].fee_code == "ZA"

    def test_v2_normalize_contra_party(self):
        """Test V2 normalization preserves contra-party type."""
        extraction = ExtractionResult(
            raw_fees=[
                {
                    "participant_type": "CUSTOMER",
                    "contra_party_type": "CUSTOMER",
                    "security_class": "PENNY",
                    "order_type": "COMPLEX",
                    "fee_type": "MAKER",
                    "amount": 0.00,
                    "is_rebate": False,
                    "notes": "Customer vs Customer, free",
                },
            ],
            confidence=0.9,
        )

        schedule = self.engine.normalize(extraction, "TEST")
        assert len(schedule.fees) == 1
        assert schedule.fees[0].contra_party_type == ParticipantType.CUSTOMER


class TestV3SchemaEnums:
    def test_exec_venue_enum_exists(self):
        from exnot.normalizer.schema import ExecVenue

        assert ExecVenue.ELECTRONIC == "ELECTRONIC"
        assert ExecVenue.FLOOR == "FLOOR"
        assert ExecVenue.ROUTED == "ROUTED"

    def test_liquidity_role_enum_exists(self):
        from exnot.normalizer.schema import LiquidityRole

        assert LiquidityRole.MAKER == "MAKER"
        assert LiquidityRole.TAKER == "TAKER"
        assert LiquidityRole.NONE == "NONE"

    def test_product_type_enum_exists(self):
        from exnot.normalizer.schema import ProductType

        assert ProductType.SIMPLE == "SIMPLE"
        assert ProductType.COMPLEX == "COMPLEX"

    def test_listing_type_enum_exists(self):
        from exnot.normalizer.schema import ListingType

        assert ListingType.EQUITY == "EQUITY"
        assert ListingType.ETF == "ETF"
        assert ListingType.INDEX == "INDEX"

    def test_penny_class_enum_exists(self):
        from exnot.normalizer.schema import PennyClass

        assert PennyClass.PENNY == "PENNY"
        assert PennyClass.NON_PENNY == "NON_PENNY"

    def test_origin_code_enum_exists(self):
        from exnot.normalizer.schema import OriginCode

        assert OriginCode.CUSTOMER == "CUSTOMER"
        assert OriginCode.PROFESSIONAL == "PROFESSIONAL"
        assert OriginCode.FIRM == "FIRM"
        assert OriginCode.BROKER_DEALER == "BROKER_DEALER"
        assert OriginCode.MARKET_MAKER == "MARKET_MAKER"
        assert OriginCode.AWAY_MARKET_MAKER == "AWAY_MARKET_MAKER"


class TestV3Normalization:
    def setup_method(self):
        self.engine = NormalizationEngine()

    def test_normalize_v3_fee(self):
        """V3-style raw fee dict should normalize correctly."""
        extraction = ExtractionResult(
            raw_fees=[
                {
                    "fee_id": "PY",
                    "fee_name": "Customer Penny Maker",
                    "origin_code": "CUSTOMER",
                    "contra_origin_code": None,
                    "product_type": "SIMPLE",
                    "listing_type": "EQUITY",
                    "penny_class": "PENNY",
                    "exec_venue": "ELECTRONIC",
                    "liquidity_role": "MAKER",
                    "auction_type": None,
                    "fee_type": "PER_CONTRACT",
                    "fee_value": -0.50,
                    "is_rebate": True,
                    "tier_level": 0,
                    "tier_condition": None,
                },
            ],
            confidence=0.95,
        )
        schedule = self.engine.normalize(extraction, "CBOE_BZX")
        assert len(schedule.fees) == 1
        fee = schedule.fees[0]
        assert fee.participant_type == ParticipantType.CUSTOMER
        assert fee.fee_type == FeeType.MAKER
        assert fee.amount == Decimal("-0.50")
        assert fee.is_rebate is True
        assert fee.security_class == SecurityClass.PENNY
        assert fee.order_type == OrderType.SIMPLE
        assert fee.fee_code == "PY"

    def test_normalize_v3_with_contra(self):
        """V3 contra_origin_code: ANY maps to NON_CUSTOMER."""
        extraction = ExtractionResult(
            raw_fees=[
                {
                    "fee_name": "Customer vs Non-Customer Complex Maker",
                    "origin_code": "CUSTOMER",
                    "contra_origin_code": "ANY",
                    "product_type": "COMPLEX",
                    "listing_type": "EQUITY",
                    "penny_class": "PENNY",
                    "exec_venue": "ELECTRONIC",
                    "liquidity_role": "MAKER",
                    "fee_type": "PER_CONTRACT",
                    "fee_value": -0.40,
                    "is_rebate": True,
                },
            ],
            confidence=0.9,
        )
        schedule = self.engine.normalize(extraction, "CBOE_BZX")
        assert schedule.fees[0].contra_party_type == ParticipantType.NON_CUSTOMER
        assert schedule.fees[0].order_type == OrderType.COMPLEX

    def test_normalize_v3_index(self):
        """V3 listing_type: INDEX should map to SecurityClass.INDEX."""
        extraction = ExtractionResult(
            raw_fees=[
                {
                    "fee_name": "RUT Index Fee",
                    "origin_code": "CUSTOMER",
                    "product_type": "SIMPLE",
                    "listing_type": "INDEX",
                    "penny_class": "NON_PENNY",
                    "symbol": "RUT",
                    "exec_venue": "ELECTRONIC",
                    "liquidity_role": "TAKER",
                    "fee_type": "PER_CONTRACT",
                    "fee_value": 0.45,
                    "is_rebate": False,
                },
            ],
            confidence=0.9,
        )
        schedule = self.engine.normalize(extraction, "CBOE_BZX")
        assert schedule.fees[0].security_class == SecurityClass.INDEX
        assert schedule.fees[0].symbol == "RUT"
        assert schedule.fees[0].fee_type == FeeType.TAKER

    def test_normalize_v3_auction(self):
        """V3 auction_type should map to appropriate order_type."""
        extraction = ExtractionResult(
            raw_fees=[
                {
                    "fee_name": "AIM Agency",
                    "origin_code": "CUSTOMER",
                    "product_type": "SIMPLE",
                    "listing_type": "EQUITY",
                    "penny_class": "PENNY",
                    "exec_venue": "ELECTRONIC",
                    "liquidity_role": "NONE",
                    "auction_type": "AIM",
                    "auction_role": "AGENCY",
                    "fee_type": "PER_CONTRACT",
                    "fee_value": 0.00,
                    "is_rebate": False,
                },
            ],
            confidence=0.9,
        )
        schedule = self.engine.normalize(extraction, "CBOE_EDGX")
        assert schedule.fees[0].order_type == OrderType.AUCTION

    def test_normalize_v3_routed(self):
        """V3 exec_venue: ROUTED should map to order_type ROUTED."""
        extraction = ExtractionResult(
            raw_fees=[
                {
                    "fee_name": "Routed Penny",
                    "origin_code": "CUSTOMER",
                    "product_type": "SIMPLE",
                    "listing_type": "EQUITY",
                    "penny_class": "PENNY",
                    "exec_venue": "ROUTED",
                    "liquidity_role": "NONE",
                    "fee_type": "PER_CONTRACT",
                    "fee_value": 0.25,
                    "is_rebate": False,
                },
            ],
            confidence=0.9,
        )
        schedule = self.engine.normalize(extraction, "CBOE_BZX")
        assert schedule.fees[0].order_type == OrderType.ROUTED

    def test_v2_still_works(self):
        """V2-format fees should still normalize correctly (no regression)."""
        extraction = ExtractionResult(
            raw_fees=[
                {
                    "participant_type": "CUSTOMER",
                    "security_class": "PENNY",
                    "order_type": "SIMPLE",
                    "fee_type": "MAKER",
                    "amount": -0.25,
                    "is_rebate": True,
                },
            ],
            confidence=0.9,
        )
        schedule = self.engine.normalize(extraction, "TEST")
        assert schedule.fees[0].participant_type == ParticipantType.CUSTOMER
        assert schedule.fees[0].fee_type == FeeType.MAKER
