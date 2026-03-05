from exnot.discovery.discoverer import UrlDiscoverer, ClassifiedCandidate


def test_classified_candidate_dataclass():
    cc = ClassifiedCandidate(
        url="https://example.com/fee_schedule.pdf",
        title="Fee Schedule",
        content_type="PDF",
        doc_category="FEE_SCHEDULE",
        classification_confidence=0.95,
        classification_reasoning="Contains fee tables",
        content_preview="Fee Schedule...",
        is_pdf=True,
        is_csv=False,
    )
    assert cc.doc_category == "FEE_SCHEDULE"
    assert cc.classification_confidence == 0.95


def test_discoverer_has_classify_method():
    assert hasattr(UrlDiscoverer, "_classify_candidates")
