from exnot.db.repositories import ExchangeDocumentRepository


def test_exchange_document_repository_exists():
    """Verify the class exists and has the expected methods."""
    assert hasattr(ExchangeDocumentRepository, "get_by_exchange")
    assert hasattr(ExchangeDocumentRepository, "get_approved_for_exchange")
    assert hasattr(ExchangeDocumentRepository, "get_pinned_for_exchange")
    assert hasattr(ExchangeDocumentRepository, "get_pending_review")
    assert hasattr(ExchangeDocumentRepository, "get_by_url")
    assert hasattr(ExchangeDocumentRepository, "create")
    assert hasattr(ExchangeDocumentRepository, "update_status")
    assert hasattr(ExchangeDocumentRepository, "upsert_by_url")
