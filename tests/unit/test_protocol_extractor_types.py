from exnot.ai.types import ExtractedBillingCode, ProtocolExtractionResult


def test_extracted_billing_code():
    code = ExtractedBillingCode(
        code="OB",
        protocol="FIX",
        description="Options Base transaction",
        tag_number=20116,
        fee_type_hint="MAKER",
    )
    assert code.code == "OB"
    assert code.tag_number == 20116


def test_protocol_extraction_result():
    result = ProtocolExtractionResult(
        billing_codes=[ExtractedBillingCode(code="OB", protocol="FIX", description="Options Base")],
        extraction_notes="Found 1 billing code in FIX spec",
    )
    assert len(result.billing_codes) == 1


def test_extracted_billing_code_defaults():
    code = ExtractedBillingCode(code="X1", description="Test")
    assert code.protocol == "OTHER"
    assert code.tag_number is None
    assert code.fee_type_hint is None
