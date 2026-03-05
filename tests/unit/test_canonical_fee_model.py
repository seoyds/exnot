from exnot.db.models import (
    BillingCode,
    BillingProtocol,
    CanonicalFee,
    NormalizedFee,
)


def test_canonical_fee_table_name():
    assert CanonicalFee.__tablename__ == "canonical_fees"


def test_canonical_fee_has_required_columns():
    col_names = {c.name for c in CanonicalFee.__table__.columns}
    required = {"id", "canonical_code", "display_name", "fee_type", "description", "category"}
    assert required.issubset(col_names)


def test_billing_code_table_name():
    assert BillingCode.__tablename__ == "billing_codes"


def test_billing_code_has_required_columns():
    col_names = {c.name for c in BillingCode.__table__.columns}
    required = {
        "id", "exchange_id", "code", "protocol", "description",
        "canonical_fee_id", "source_document_id", "effective_date", "tag_number",
    }
    assert required.issubset(col_names)


def test_billing_protocol_enum():
    assert BillingProtocol.FIX.value == "FIX"
    assert BillingProtocol.BINARY.value == "BINARY"


def test_normalized_fee_has_canonical_fee_id():
    col_names = {c.name for c in NormalizedFee.__table__.columns}
    assert "canonical_fee_id" in col_names
    assert "exchange_fee_code" in col_names
    assert "exchange_fee_name" in col_names
