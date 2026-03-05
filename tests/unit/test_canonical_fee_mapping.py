from exnot.ai.types import ExtractedFee


def test_extracted_fee_has_canonical_fields():
    fee = ExtractedFee(
        participant_type="CUSTOMER",
        security_class="PENNY",
        order_type="SIMPLE",
        fee_type="MAKER",
        amount=-0.25,
        exchange_fee_code="OB",
        exchange_fee_name="Options Base Rate",
        suggested_canonical_code="MAKER_REBATE",
    )
    assert fee.exchange_fee_code == "OB"
    assert fee.exchange_fee_name == "Options Base Rate"
    assert fee.suggested_canonical_code == "MAKER_REBATE"


def test_extracted_fee_canonical_fields_optional():
    fee = ExtractedFee(
        participant_type="CUSTOMER",
        security_class="PENNY",
        order_type="SIMPLE",
        fee_type="MAKER",
        amount=-0.25,
    )
    assert fee.exchange_fee_code is None
    assert fee.exchange_fee_name is None
    assert fee.suggested_canonical_code is None
