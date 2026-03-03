"""Tests for the exchange registry."""

from exnot.exchanges.registry import get_all_exchanges, load_all_definitions


class TestExchangeRegistry:
    def test_load_all_definitions(self):
        """All 19 YAML files should load successfully."""
        definitions = load_all_definitions()
        assert len(definitions) == 19

    def test_all_definitions_have_required_fields(self):
        definitions = load_all_definitions()
        required_fields = ["code", "name", "operator", "fee_schedule_url", "fee_schedule_format", "scraper_type"]
        for defn in definitions:
            for field in required_fields:
                assert field in defn, f"Missing {field} in {defn.get('code', 'unknown')}"

    def test_unique_codes(self):
        definitions = load_all_definitions()
        codes = [d["code"] for d in definitions]
        assert len(codes) == len(set(codes)), "Duplicate exchange codes found"

    def test_get_all_exchanges(self):
        exchanges = get_all_exchanges()
        assert len(exchanges) == 19

        # Check some known exchanges
        codes = {e.code for e in exchanges}
        assert "CBOE_C1" in codes
        assert "NYSE_ARCA" in codes
        assert "NASDAQ_PHLX" in codes
        assert "MIAX_OPTIONS" in codes
        assert "BOX_OPTIONS" in codes
        assert "MEMX_OPTIONS" in codes
        assert "NASDAQ_NTX" in codes  # Placeholder

    def test_inactive_exchange(self):
        exchanges = get_all_exchanges()
        ntx = next(e for e in exchanges if e.code == "NASDAQ_NTX")
        assert ntx.is_active is False

    def test_exchange_operators(self):
        """Verify the 5 major operators are represented."""
        exchanges = get_all_exchanges()
        operators = {e.operator for e in exchanges}
        assert any("Cboe" in o for o in operators)
        assert any("Nasdaq" in o for o in operators)
        assert any("NYSE" in o or "ICE" in o or "Intercontinental" in o for o in operators)
        assert any("MIAX" in o or "Miami" in o for o in operators)
