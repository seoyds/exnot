from exnot.db.repositories import CanonicalFeeRepository, BillingCodeRepository


def test_canonical_fee_repository_exists():
    assert hasattr(CanonicalFeeRepository, "get_all")
    assert hasattr(CanonicalFeeRepository, "get_by_code")
    assert hasattr(CanonicalFeeRepository, "get_by_id")
    assert hasattr(CanonicalFeeRepository, "seed_from_yaml")


def test_billing_code_repository_exists():
    assert hasattr(BillingCodeRepository, "get_by_exchange")
    assert hasattr(BillingCodeRepository, "upsert")
