from exnot.ai.types import DocumentClassificationResult


def test_doc_classification_result_fields():
    result = DocumentClassificationResult(
        doc_category="FEE_SCHEDULE",
        confidence=0.95,
        reasoning="Contains fee schedule tables with per-contract pricing",
    )
    assert result.doc_category == "FEE_SCHEDULE"
    assert result.confidence == 0.95
    assert result.reasoning


def test_doc_classification_result_valid_categories():
    valid = {"FEE_SCHEDULE", "PROTOCOL_SPEC", "REGULATORY_FILING", "MEMBERSHIP_AGREEMENT", "CIRCULAR_NOTICE", "OTHER"}
    for cat in valid:
        result = DocumentClassificationResult(doc_category=cat, confidence=0.5, reasoning="test")
        assert result.doc_category == cat
