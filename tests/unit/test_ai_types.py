"""Tests for AI output types (field validators, serialization)."""

import pytest
from pydantic import ValidationError

from exnot.ai.types import (
    ChangeSummary,
    CorrectionResult,
    ExtractedFee,
    OrchestratorResult,
    SectionExtractionResult,
    TierCondition,
    TierConditionCriterion,
    UrlEvaluationResult,
    ValidationIssue,
    ValidationResult,
)


class TestExtractedFee:
    def test_valid_fee(self):
        fee = ExtractedFee(
            participant_type="CUSTOMER",
            security_class="PENNY",
            order_type="SIMPLE",
            fee_type="MAKER",
            amount=-0.50,
            is_rebate=True,
        )
        assert fee.amount == -0.50
        assert fee.is_rebate is True
        assert fee.fee_unit == "PER_CONTRACT"

    def test_amount_exceeds_limit(self):
        with pytest.raises(ValidationError, match="exceeds"):
            ExtractedFee(
                participant_type="CUSTOMER",
                security_class="PENNY",
                order_type="SIMPLE",
                fee_type="TAKER",
                amount=15.00,
            )

    def test_amount_at_boundary(self):
        fee = ExtractedFee(
            participant_type="CUSTOMER",
            security_class="PENNY",
            order_type="SIMPLE",
            fee_type="TAKER",
            amount=10.0,
        )
        assert fee.amount == 10.0

    def test_optional_fields_default_none(self):
        fee = ExtractedFee(
            participant_type="MARKET_MAKER",
            security_class="NON_PENNY",
            order_type="COMPLEX",
            fee_type="TAKER",
            amount=0.45,
        )
        assert fee.fee_code is None
        assert fee.contra_party_type is None
        assert fee.symbol is None
        assert fee.tier_group is None
        assert fee.tier_conditions is None

    def test_with_tier_conditions(self):
        fee = ExtractedFee(
            participant_type="CUSTOMER",
            security_class="PENNY",
            order_type="SIMPLE",
            fee_type="MAKER",
            amount=-0.52,
            is_rebate=True,
            tier_group="customer_penny_add",
            tier_number=1,
            tier_conditions=TierCondition(
                logic="AND",
                criteria=[
                    TierConditionCriterion(
                        metric="ADAV",
                        capacities=["CUSTOMER"],
                        operator=">=",
                        value=0.005,
                        unit="PCT_OCV",
                        description="Customer ADAV >= 0.50% of OCV",
                    )
                ],
            ),
        )
        assert fee.tier_conditions.logic == "AND"
        assert len(fee.tier_conditions.criteria) == 1

    def test_serialization_roundtrip(self):
        fee = ExtractedFee(
            participant_type="CUSTOMER",
            security_class="PENNY",
            order_type="SIMPLE",
            fee_type="MAKER",
            amount=-0.50,
            is_rebate=True,
            fee_code="PY",
        )
        d = fee.model_dump()
        fee2 = ExtractedFee.model_validate(d)
        assert fee2.amount == fee.amount
        assert fee2.fee_code == fee.fee_code


class TestSectionExtractionResult:
    def test_empty_default(self):
        result = SectionExtractionResult()
        assert result.fees == []
        assert result.exchange_name == ""

    def test_with_fees(self):
        result = SectionExtractionResult(
            exchange_name="CBOE BZX",
            effective_date="2025-01-15",
            fees=[
                ExtractedFee(
                    participant_type="CUSTOMER",
                    security_class="PENNY",
                    order_type="SIMPLE",
                    fee_type="MAKER",
                    amount=-0.50,
                    is_rebate=True,
                ),
            ],
        )
        assert len(result.fees) == 1
        assert result.exchange_name == "CBOE BZX"


class TestValidationResult:
    def test_valid(self):
        result = ValidationResult(is_valid=True, confidence=0.95)
        assert result.issues == []

    def test_with_issues(self):
        result = ValidationResult(
            is_valid=False,
            confidence=0.5,
            issues=[
                ValidationIssue(
                    severity="WARNING",
                    category="MISSING_PARTICIPANT",
                    message="Missing CUSTOMER fees",
                ),
            ],
            suggested_actions=["Extract section 3 for Customer fees"],
        )
        assert len(result.issues) == 1
        assert not result.is_valid


class TestCorrectionResult:
    def test_empty(self):
        result = CorrectionResult()
        assert result.corrections == []
        assert result.removed_indices == []


class TestOrchestratorResult:
    def test_empty(self):
        result = OrchestratorResult()
        assert result.fees == []

    def test_serialization_roundtrip(self):
        result = OrchestratorResult(
            exchange_name="Test Exchange",
            effective_date="2025-01-01",
            fees=[
                ExtractedFee(
                    participant_type="CUSTOMER",
                    security_class="PENNY",
                    order_type="SIMPLE",
                    fee_type="TAKER",
                    amount=0.49,
                ),
            ],
            validation_confidence=0.9,
        )
        d = result.model_dump()
        result2 = OrchestratorResult.model_validate(d)
        assert len(result2.fees) == 1
        assert result2.validation_confidence == 0.9


class TestUrlEvaluationResult:
    def test_defaults(self):
        result = UrlEvaluationResult()
        assert result.primary_url is None
        assert result.recommended_format == "HTML"


class TestChangeSummary:
    def test_defaults(self):
        result = ChangeSummary()
        assert result.impact_level == "LOW"
        assert result.key_changes == []


class TestExtractedFeeV3:
    """Tests for the new per-exchange schema fields."""

    def test_new_schema_fields(self):
        fee = ExtractedFee(
            fee_id="PY",
            fee_name="Customer Penny Maker",
            origin_code="CUSTOMER",
            contra_origin_code="ANY",
            product_type="SIMPLE",
            contra_product_type=None,
            listing_type="EQUITY",
            penny_class="PENNY",
            multi_listed=True,
            symbol="SPY",
            exec_venue="ELECTRONIC",
            liquidity_role="MAKER",
            auction_type=None,
            auction_role=None,
            fee_type="PER_CONTRACT",
            fee_value=-0.50,
            is_rebate=True,
            tier_level=0,
            tier_condition=None,
        )
        assert fee.origin_code == "CUSTOMER"
        assert fee.exec_venue == "ELECTRONIC"
        assert fee.fee_value == -0.50
        assert fee.fee_id == "PY"

    def test_minimal_fee_new_schema(self):
        """Minimal fee with only required new fields."""
        fee = ExtractedFee(
            fee_name="Test Fee",
            origin_code="MARKET_MAKER",
            product_type="SIMPLE",
            listing_type="EQUITY",
            penny_class="PENNY",
            exec_venue="ELECTRONIC",
            liquidity_role="TAKER",
            fee_type="PER_CONTRACT",
            fee_value=0.50,
            is_rebate=False,
        )
        assert fee.contra_origin_code is None
        assert fee.fee_id is None
        assert fee.tier_level is None

    def test_fee_value_validation(self):
        """fee_value exceeding $10/contract should fail for PER_CONTRACT."""
        with pytest.raises(ValidationError, match="exceeds"):
            ExtractedFee(
                fee_name="Bad Fee",
                origin_code="CUSTOMER",
                product_type="SIMPLE",
                listing_type="EQUITY",
                penny_class="PENNY",
                exec_venue="ELECTRONIC",
                liquidity_role="TAKER",
                fee_type="PER_CONTRACT",
                fee_value=15.00,
                is_rebate=False,
            )

    def test_backward_compat_old_fields(self):
        """Old-style fields should still work (backward compat during transition)."""
        fee = ExtractedFee(
            participant_type="CUSTOMER",
            security_class="PENNY",
            order_type="SIMPLE",
            fee_type="MAKER",
            amount=-0.50,
            is_rebate=True,
        )
        assert fee.participant_type == "CUSTOMER"
        assert fee.amount == -0.50
