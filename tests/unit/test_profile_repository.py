"""Tests for ExchangeProfileRepository (import-only, no DB)."""

from exnot.db.repositories import ExchangeProfileRepository


def test_repository_class_exists():
    """Verify the repository class can be imported."""
    assert ExchangeProfileRepository is not None
