from exnot.db.models import (
    DocumentCategory,
    DocumentStatus,
    ExchangeDocument,
)


def test_document_category_enum_values():
    assert DocumentCategory.FEE_SCHEDULE.value == "FEE_SCHEDULE"
    assert DocumentCategory.PROTOCOL_SPEC.value == "PROTOCOL_SPEC"
    assert DocumentCategory.REGULATORY_FILING.value == "REGULATORY_FILING"
    assert DocumentCategory.MEMBERSHIP_AGREEMENT.value == "MEMBERSHIP_AGREEMENT"
    assert DocumentCategory.CIRCULAR_NOTICE.value == "CIRCULAR_NOTICE"
    assert DocumentCategory.OTHER.value == "OTHER"


def test_document_status_enum_values():
    assert DocumentStatus.DISCOVERED.value == "DISCOVERED"
    assert DocumentStatus.CLASSIFIED.value == "CLASSIFIED"
    assert DocumentStatus.APPROVED.value == "APPROVED"
    assert DocumentStatus.REJECTED.value == "REJECTED"
    assert DocumentStatus.STALE.value == "STALE"


def test_exchange_document_table_name():
    assert ExchangeDocument.__tablename__ == "exchange_documents"


def test_exchange_document_has_required_columns():
    col_names = {c.name for c in ExchangeDocument.__table__.columns}
    required = {
        "id", "exchange_id", "source_url", "url_pattern", "title",
        "content_type", "doc_category", "status", "is_pinned", "is_primary",
        "classification_confidence", "classification_reasoning", "admin_notes",
        "last_seen_at", "last_fetched_hash", "discovered_at", "approved_at",
        "approved_by", "created_at", "updated_at",
    }
    assert required.issubset(col_names)
