"""Tests for ExchangeProfile model."""

import uuid

from exnot.db.models import ExchangeProfile, ProfileStatus


def test_profile_status_enum():
    assert ProfileStatus.LEARNING.value == "LEARNING"
    assert ProfileStatus.ACTIVE.value == "ACTIVE"
    assert ProfileStatus.NEEDS_UPDATE.value == "NEEDS_UPDATE"


def test_exchange_profile_creation():
    profile = ExchangeProfile(
        exchange_id=uuid.uuid4(),
        profile_version=1,
        table_mappings=[],
        table_fingerprints={},
        section_metadata={},
        extraction_stats={},
        status=ProfileStatus.LEARNING,
    )
    assert profile.profile_version == 1
    assert profile.status == ProfileStatus.LEARNING
    assert profile.table_mappings == []
