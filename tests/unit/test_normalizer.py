"""Tests for the normalization engine."""

from decimal import Decimal

from exnot.normalizer.engine import NormalizationEngine
from exnot.normalizer.schema import FeeType, ParticipantType, SecurityClass
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
