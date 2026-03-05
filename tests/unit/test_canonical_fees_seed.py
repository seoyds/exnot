from pathlib import Path

import yaml


def test_canonical_fees_yaml_exists():
    path = Path(__file__).parent.parent.parent / "src" / "exnot" / "exchanges" / "canonical_fees.yml"
    assert path.exists()


def test_canonical_fees_yaml_structure():
    path = Path(__file__).parent.parent.parent / "src" / "exnot" / "exchanges" / "canonical_fees.yml"
    data = yaml.safe_load(path.read_text())
    assert "fees" in data
    assert len(data["fees"]) >= 20

    first = data["fees"][0]
    assert "canonical_code" in first
    assert "display_name" in first
    assert "fee_type" in first
    assert "category" in first


def test_canonical_codes_are_unique():
    path = Path(__file__).parent.parent.parent / "src" / "exnot" / "exchanges" / "canonical_fees.yml"
    data = yaml.safe_load(path.read_text())
    codes = [f["canonical_code"] for f in data["fees"]]
    assert len(codes) == len(set(codes)), f"Duplicate codes found: {[c for c in codes if codes.count(c) > 1]}"


def test_canonical_fee_types_are_valid():
    """All fee_type values should be valid FeeType enum members."""
    from exnot.db.models import FeeType

    path = Path(__file__).parent.parent.parent / "src" / "exnot" / "exchanges" / "canonical_fees.yml"
    data = yaml.safe_load(path.read_text())
    valid_types = {ft.value for ft in FeeType}
    for fee in data["fees"]:
        assert fee["fee_type"] in valid_types, f"Invalid fee_type '{fee['fee_type']}' for {fee['canonical_code']}"
