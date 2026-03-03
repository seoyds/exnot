"""End-to-end extraction test for NASDAQ ISE (HTML path).

Exercises the full pipeline:  HTML Parse → AI Extract → Normalize → Diff
with all external services mocked at the boundary.
"""

from decimal import Decimal
from unittest.mock import patch

from exnot.differ.detector import ChangeDetector
from exnot.normalizer.engine import NormalizationEngine
from exnot.normalizer.schema import (
    FeeType,
    OrderType,
    ParticipantType,
    SecurityClass,
)
from exnot.parser.ai_extractor import AIExtractor, ExtractionResult
from exnot.parser.html_parser import HtmlParser

# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

NASDAQ_ISE_HTML = b"""\
<html><body>
<h1>Nasdaq ISE Options Exchange Fee Schedule</h1>
<p>Effective February 1, 2026</p>

<h2>Regular Order Transaction Fees - Select Symbols (Penny Pilot)</h2>
<table>
  <tr>
    <th>Participant Type</th>
    <th>Maker (per contract)</th>
    <th>Taker (per contract)</th>
  </tr>
  <tr><td>Priority Customer</td><td>-$0.25</td><td>$0.50</td></tr>
  <tr><td>Professional Customer</td><td>$0.20</td><td>$0.50</td></tr>
  <tr><td>Market Maker</td><td>-$0.15</td><td>$0.47</td></tr>
  <tr><td>Non-Nasdaq ISE Market Maker</td><td>$0.30</td><td>$0.50</td></tr>
  <tr><td>Firm</td><td>$0.20</td><td>$0.50</td></tr>
  <tr><td>Broker-Dealer</td><td>$0.20</td><td>$0.50</td></tr>
</table>

<h2>Regular Order Transaction Fees - Non-Select Symbols (Non-Penny)</h2>
<table>
  <tr>
    <th>Participant Type</th>
    <th>Maker (per contract)</th>
    <th>Taker (per contract)</th>
  </tr>
  <tr><td>Priority Customer</td><td>-$0.42</td><td>$0.85</td></tr>
  <tr><td>Professional Customer</td><td>$0.25</td><td>$0.85</td></tr>
  <tr><td>Market Maker</td><td>-$0.10</td><td>$0.82</td></tr>
  <tr><td>Firm</td><td>$0.25</td><td>$0.85</td></tr>
  <tr><td>Broker-Dealer</td><td>$0.25</td><td>$0.85</td></tr>
</table>

<h2>Complex Order Fees</h2>
<table>
  <tr>
    <th>Participant Type</th>
    <th>Maker (per contract)</th>
    <th>Taker (per contract)</th>
  </tr>
  <tr><td>Priority Customer</td><td>$0.00</td><td>$0.00</td></tr>
  <tr><td>Professional Customer</td><td>$0.20</td><td>$0.50</td></tr>
  <tr><td>Market Maker</td><td>$0.20</td><td>$0.50</td></tr>
</table>
</body></html>
"""

# What the AI extractor would return for the above HTML
MOCK_EXTRACTION_RESULT = ExtractionResult(
    raw_fees=[
        # Penny — Maker
        {
            "participant_type": "CUSTOMER",
            "security_class": "PENNY",
            "order_type": "SIMPLE",
            "fee_type": "MAKER",
            "amount": -0.25,
            "is_rebate": True,
            "section_ref": "Regular Order Transaction Fees - Select Symbols",
        },
        {
            "participant_type": "PROFESSIONAL",
            "security_class": "PENNY",
            "order_type": "SIMPLE",
            "fee_type": "MAKER",
            "amount": 0.20,
            "is_rebate": False,
            "section_ref": "Regular Order Transaction Fees - Select Symbols",
        },
        {
            "participant_type": "MARKET_MAKER",
            "security_class": "PENNY",
            "order_type": "SIMPLE",
            "fee_type": "MAKER",
            "amount": -0.15,
            "is_rebate": True,
            "section_ref": "Regular Order Transaction Fees - Select Symbols",
        },
        {
            "participant_type": "AWAY_MARKET_MAKER",
            "security_class": "PENNY",
            "order_type": "SIMPLE",
            "fee_type": "MAKER",
            "amount": 0.30,
            "is_rebate": False,
            "section_ref": "Regular Order Transaction Fees - Select Symbols",
        },
        {
            "participant_type": "FIRM",
            "security_class": "PENNY",
            "order_type": "SIMPLE",
            "fee_type": "MAKER",
            "amount": 0.20,
            "is_rebate": False,
            "section_ref": "Regular Order Transaction Fees - Select Symbols",
        },
        {
            "participant_type": "BROKER_DEALER",
            "security_class": "PENNY",
            "order_type": "SIMPLE",
            "fee_type": "MAKER",
            "amount": 0.20,
            "is_rebate": False,
            "section_ref": "Regular Order Transaction Fees - Select Symbols",
        },
        # Penny — Taker
        {
            "participant_type": "CUSTOMER",
            "security_class": "PENNY",
            "order_type": "SIMPLE",
            "fee_type": "TAKER",
            "amount": 0.50,
            "is_rebate": False,
            "section_ref": "Regular Order Transaction Fees - Select Symbols",
        },
        {
            "participant_type": "PROFESSIONAL",
            "security_class": "PENNY",
            "order_type": "SIMPLE",
            "fee_type": "TAKER",
            "amount": 0.50,
            "is_rebate": False,
            "section_ref": "Regular Order Transaction Fees - Select Symbols",
        },
        {
            "participant_type": "MARKET_MAKER",
            "security_class": "PENNY",
            "order_type": "SIMPLE",
            "fee_type": "TAKER",
            "amount": 0.47,
            "is_rebate": False,
            "section_ref": "Regular Order Transaction Fees - Select Symbols",
        },
        {
            "participant_type": "AWAY_MARKET_MAKER",
            "security_class": "PENNY",
            "order_type": "SIMPLE",
            "fee_type": "TAKER",
            "amount": 0.50,
            "is_rebate": False,
            "section_ref": "Regular Order Transaction Fees - Select Symbols",
        },
        {
            "participant_type": "FIRM",
            "security_class": "PENNY",
            "order_type": "SIMPLE",
            "fee_type": "TAKER",
            "amount": 0.50,
            "is_rebate": False,
            "section_ref": "Regular Order Transaction Fees - Select Symbols",
        },
        {
            "participant_type": "BROKER_DEALER",
            "security_class": "PENNY",
            "order_type": "SIMPLE",
            "fee_type": "TAKER",
            "amount": 0.50,
            "is_rebate": False,
            "section_ref": "Regular Order Transaction Fees - Select Symbols",
        },
        # Non-Penny — Maker
        {
            "participant_type": "CUSTOMER",
            "security_class": "NON_PENNY",
            "order_type": "SIMPLE",
            "fee_type": "MAKER",
            "amount": -0.42,
            "is_rebate": True,
            "section_ref": "Regular Order Transaction Fees - Non-Select Symbols",
        },
        {
            "participant_type": "PROFESSIONAL",
            "security_class": "NON_PENNY",
            "order_type": "SIMPLE",
            "fee_type": "MAKER",
            "amount": 0.25,
            "is_rebate": False,
            "section_ref": "Regular Order Transaction Fees - Non-Select Symbols",
        },
        {
            "participant_type": "MARKET_MAKER",
            "security_class": "NON_PENNY",
            "order_type": "SIMPLE",
            "fee_type": "MAKER",
            "amount": -0.10,
            "is_rebate": True,
            "section_ref": "Regular Order Transaction Fees - Non-Select Symbols",
        },
        {
            "participant_type": "FIRM",
            "security_class": "NON_PENNY",
            "order_type": "SIMPLE",
            "fee_type": "MAKER",
            "amount": 0.25,
            "is_rebate": False,
            "section_ref": "Regular Order Transaction Fees - Non-Select Symbols",
        },
        {
            "participant_type": "BROKER_DEALER",
            "security_class": "NON_PENNY",
            "order_type": "SIMPLE",
            "fee_type": "MAKER",
            "amount": 0.25,
            "is_rebate": False,
            "section_ref": "Regular Order Transaction Fees - Non-Select Symbols",
        },
        # Non-Penny — Taker
        {
            "participant_type": "CUSTOMER",
            "security_class": "NON_PENNY",
            "order_type": "SIMPLE",
            "fee_type": "TAKER",
            "amount": 0.85,
            "is_rebate": False,
            "section_ref": "Regular Order Transaction Fees - Non-Select Symbols",
        },
        {
            "participant_type": "PROFESSIONAL",
            "security_class": "NON_PENNY",
            "order_type": "SIMPLE",
            "fee_type": "TAKER",
            "amount": 0.85,
            "is_rebate": False,
            "section_ref": "Regular Order Transaction Fees - Non-Select Symbols",
        },
        {
            "participant_type": "MARKET_MAKER",
            "security_class": "NON_PENNY",
            "order_type": "SIMPLE",
            "fee_type": "TAKER",
            "amount": 0.82,
            "is_rebate": False,
            "section_ref": "Regular Order Transaction Fees - Non-Select Symbols",
        },
        {
            "participant_type": "FIRM",
            "security_class": "NON_PENNY",
            "order_type": "SIMPLE",
            "fee_type": "TAKER",
            "amount": 0.85,
            "is_rebate": False,
            "section_ref": "Regular Order Transaction Fees - Non-Select Symbols",
        },
        {
            "participant_type": "BROKER_DEALER",
            "security_class": "NON_PENNY",
            "order_type": "SIMPLE",
            "fee_type": "TAKER",
            "amount": 0.85,
            "is_rebate": False,
            "section_ref": "Regular Order Transaction Fees - Non-Select Symbols",
        },
        # Complex
        {
            "participant_type": "CUSTOMER",
            "security_class": "PENNY",
            "order_type": "COMPLEX",
            "fee_type": "MAKER",
            "amount": 0.00,
            "is_rebate": False,
            "section_ref": "Complex Order Fees",
        },
        {
            "participant_type": "CUSTOMER",
            "security_class": "PENNY",
            "order_type": "COMPLEX",
            "fee_type": "TAKER",
            "amount": 0.00,
            "is_rebate": False,
            "section_ref": "Complex Order Fees",
        },
        {
            "participant_type": "PROFESSIONAL",
            "security_class": "PENNY",
            "order_type": "COMPLEX",
            "fee_type": "MAKER",
            "amount": 0.20,
            "is_rebate": False,
            "section_ref": "Complex Order Fees",
        },
        {
            "participant_type": "PROFESSIONAL",
            "security_class": "PENNY",
            "order_type": "COMPLEX",
            "fee_type": "TAKER",
            "amount": 0.50,
            "is_rebate": False,
            "section_ref": "Complex Order Fees",
        },
        {
            "participant_type": "MARKET_MAKER",
            "security_class": "PENNY",
            "order_type": "COMPLEX",
            "fee_type": "MAKER",
            "amount": 0.20,
            "is_rebate": False,
            "section_ref": "Complex Order Fees",
        },
        {
            "participant_type": "MARKET_MAKER",
            "security_class": "PENNY",
            "order_type": "COMPLEX",
            "fee_type": "TAKER",
            "amount": 0.50,
            "is_rebate": False,
            "section_ref": "Complex Order Fees",
        },
    ],
    exchange_name="Nasdaq ISE",
    effective_date="February 1, 2026",
    confidence=0.92,
    extraction_notes="Extracted penny, non-penny, and complex order fees.",
    ai_calls_made=3,
    total_tokens_used=8500,
)

EXCHANGE_CODE = "NASDAQ_ISE"


# ---------------------------------------------------------------------------
# Step 1: HTML Parsing
# ---------------------------------------------------------------------------


class TestHtmlParsing:
    """Verify HtmlParser extracts tables and text from the NASDAQ ISE fixture."""

    def setup_method(self):
        self.parser = HtmlParser()
        self.doc = self.parser.extract(NASDAQ_ISE_HTML)

    def test_extracts_three_tables(self):
        assert len(self.doc.tables) == 3

    def test_penny_table_headers(self):
        table = self.doc.tables[0]
        assert table.headers == ["Participant Type", "Maker (per contract)", "Taker (per contract)"]

    def test_penny_table_has_six_rows(self):
        assert len(self.doc.tables[0].rows) == 6

    def test_penny_table_first_row(self):
        assert self.doc.tables[0].rows[0] == ["Priority Customer", "-$0.25", "$0.50"]

    def test_non_penny_table_has_five_rows(self):
        assert len(self.doc.tables[1].rows) == 5

    def test_complex_table_has_three_rows(self):
        assert len(self.doc.tables[2].rows) == 3

    def test_full_text_contains_heading(self):
        assert "Nasdaq ISE Options Exchange Fee Schedule" in self.doc.full_text

    def test_full_text_contains_effective_date(self):
        assert "February 1, 2026" in self.doc.full_text

    def test_table_title_from_preceding_heading(self):
        # The parser picks the nearest preceding heading as title
        assert "Select Symbols" in self.doc.tables[0].title or "Penny" in self.doc.tables[0].title


# ---------------------------------------------------------------------------
# Step 2: AI Extraction (mocked)
# ---------------------------------------------------------------------------


class TestAIExtraction:
    """Verify the mock extraction result has the expected shape."""

    def test_raw_fee_count(self):
        assert len(MOCK_EXTRACTION_RESULT.raw_fees) == 28

    def test_all_fees_have_required_fields(self):
        required = {"participant_type", "security_class", "order_type", "fee_type", "amount", "is_rebate"}
        for fee in MOCK_EXTRACTION_RESULT.raw_fees:
            assert required.issubset(fee.keys()), f"Missing keys in {fee}"

    def test_exchange_name(self):
        assert MOCK_EXTRACTION_RESULT.exchange_name == "Nasdaq ISE"

    def test_effective_date_parsed(self):
        assert MOCK_EXTRACTION_RESULT.effective_date == "February 1, 2026"

    def test_confidence_in_range(self):
        assert 0.0 <= MOCK_EXTRACTION_RESULT.confidence <= 1.0

    @patch.object(AIExtractor, "extract", return_value=MOCK_EXTRACTION_RESULT)
    def test_extractor_returns_mock(self, mock_extract):
        parser = HtmlParser()
        doc = parser.extract(NASDAQ_ISE_HTML)
        extractor = AIExtractor()
        result = extractor.extract(doc, EXCHANGE_CODE)
        assert result is MOCK_EXTRACTION_RESULT
        mock_extract.assert_called_once()


# ---------------------------------------------------------------------------
# Step 3: Normalization
# ---------------------------------------------------------------------------


class TestNormalization:
    """Verify NormalizationEngine produces a correct NormalizedFeeSchedule."""

    def setup_method(self):
        engine = NormalizationEngine()
        self.schedule = engine.normalize(MOCK_EXTRACTION_RESULT, EXCHANGE_CODE)

    def test_exchange_code(self):
        assert self.schedule.exchange_code == EXCHANGE_CODE

    def test_exchange_name(self):
        assert self.schedule.exchange_name == "Nasdaq ISE"

    def test_effective_date(self):
        from datetime import date

        assert self.schedule.effective_date == date(2026, 2, 1)

    def test_all_fees_normalized(self):
        assert len(self.schedule.fees) == 28

    def test_participant_type_mapping(self):
        types = {f.participant_type for f in self.schedule.fees}
        assert ParticipantType.CUSTOMER in types
        assert ParticipantType.PROFESSIONAL in types
        assert ParticipantType.MARKET_MAKER in types
        assert ParticipantType.FIRM in types
        assert ParticipantType.BROKER_DEALER in types

    def test_security_classes_present(self):
        classes = {f.security_class for f in self.schedule.fees}
        assert SecurityClass.PENNY in classes
        assert SecurityClass.NON_PENNY in classes

    def test_order_types_present(self):
        types = {f.order_type for f in self.schedule.fees}
        assert OrderType.SIMPLE in types
        assert OrderType.COMPLEX in types

    def test_fee_types_present(self):
        types = {f.fee_type for f in self.schedule.fees}
        assert FeeType.MAKER in types
        assert FeeType.TAKER in types

    def test_rebate_signs(self):
        """Rebates must have negative amounts; fees must have non-negative."""
        for fee in self.schedule.fees:
            if fee.is_rebate:
                assert fee.amount < 0, f"Rebate has positive amount: {fee}"
            else:
                assert fee.amount >= 0, f"Fee has negative amount: {fee}"

    def test_customer_penny_maker_rebate(self):
        matches = self.schedule.get_fees(
            participant_type=ParticipantType.CUSTOMER,
            security_class=SecurityClass.PENNY,
            fee_type=FeeType.MAKER,
            order_type=OrderType.SIMPLE,
        )
        assert len(matches) == 1
        assert matches[0].amount == Decimal("-0.25")
        assert matches[0].is_rebate is True
        assert matches[0].amount_cents == -2500

    def test_market_maker_penny_taker(self):
        matches = self.schedule.get_fees(
            participant_type=ParticipantType.MARKET_MAKER,
            security_class=SecurityClass.PENNY,
            fee_type=FeeType.TAKER,
            order_type=OrderType.SIMPLE,
        )
        assert len(matches) == 1
        assert matches[0].amount == Decimal("0.47")
        assert matches[0].amount_cents == 4700

    def test_customer_non_penny_maker_rebate(self):
        matches = self.schedule.get_fees(
            participant_type=ParticipantType.CUSTOMER,
            security_class=SecurityClass.NON_PENNY,
            fee_type=FeeType.MAKER,
            order_type=OrderType.SIMPLE,
        )
        assert len(matches) == 1
        assert matches[0].amount == Decimal("-0.42")
        assert matches[0].is_rebate is True

    def test_complex_customer_zero_fee(self):
        matches = self.schedule.get_fees(
            participant_type=ParticipantType.CUSTOMER,
            fee_type=FeeType.MAKER,
            order_type=OrderType.COMPLEX,
        )
        assert len(matches) == 1
        assert matches[0].amount == Decimal("0.00")
        assert matches[0].is_rebate is False


# ---------------------------------------------------------------------------
# Step 4: Change Detection
# ---------------------------------------------------------------------------


class TestChangeDetection:
    """Verify ChangeDetector correctly identifies changes."""

    def setup_method(self):
        engine = NormalizationEngine()
        self.schedule = engine.normalize(MOCK_EXTRACTION_RESULT, EXCHANGE_CODE)
        self.detector = ChangeDetector()

    def test_first_run_all_new(self):
        """First extraction with no prior version should mark all fees as NEW."""
        report = self.detector.detect(
            old_schedule=None,
            new_schedule=self.schedule,
            old_version=None,
            new_version=1,
        )
        assert report.has_changes is True
        assert report.new_count == 28
        assert report.modified_count == 0
        assert report.removed_count == 0
        assert report.exchange_code == EXCHANGE_CODE

    def test_unchanged_schedule_no_changes(self):
        """Comparing identical schedules should detect no changes."""
        report = self.detector.detect(
            old_schedule=self.schedule,
            new_schedule=self.schedule,
            old_version=1,
            new_version=2,
        )
        assert report.has_changes is False
        assert len(report.changes) == 0

    def test_modified_fee_detected(self):
        """Changing one fee amount should produce a MODIFIED entry."""
        # Create a modified version with different Customer penny taker
        modified_fees = [dict(f) for f in MOCK_EXTRACTION_RESULT.raw_fees]
        # Fee at index 6 is CUSTOMER/PENNY/SIMPLE/TAKER @ $0.50
        modified_fees[6] = {**modified_fees[6], "amount": 0.52}

        modified_extraction = ExtractionResult(
            raw_fees=modified_fees,
            exchange_name="Nasdaq ISE",
            effective_date="March 1, 2026",
            confidence=0.92,
        )
        engine = NormalizationEngine()
        modified_schedule = engine.normalize(modified_extraction, EXCHANGE_CODE)

        report = self.detector.detect(
            old_schedule=self.schedule,
            new_schedule=modified_schedule,
            old_version=1,
            new_version=2,
        )
        assert report.has_changes is True
        assert report.modified_count == 1
        change = [c for c in report.changes if c.change_type == "MODIFIED"][0]
        assert change.participant_type == "CUSTOMER"
        assert change.fee_type == "TAKER"
        assert change.old_amount_cents == 5000
        assert change.new_amount_cents == 5200

    def test_new_fee_detected(self):
        """Adding a new fee should produce a NEW entry."""
        added_fees = list(MOCK_EXTRACTION_RESULT.raw_fees) + [
            {
                "participant_type": "CUSTOMER",
                "security_class": "PENNY",
                "order_type": "SIMPLE",
                "fee_type": "ROUTING",
                "amount": 0.15,
                "is_rebate": False,
            },
        ]
        added_extraction = ExtractionResult(
            raw_fees=added_fees,
            exchange_name="Nasdaq ISE",
            confidence=0.92,
        )
        engine = NormalizationEngine()
        added_schedule = engine.normalize(added_extraction, EXCHANGE_CODE)

        report = self.detector.detect(
            old_schedule=self.schedule,
            new_schedule=added_schedule,
            old_version=1,
            new_version=2,
        )
        assert report.new_count == 1
        new_change = [c for c in report.changes if c.change_type == "NEW"][0]
        assert new_change.fee_type == "ROUTING"

    def test_removed_fee_detected(self):
        """Removing a fee should produce a REMOVED entry."""
        # Remove the last fee (MM/COMPLEX/TAKER)
        fewer_fees = MOCK_EXTRACTION_RESULT.raw_fees[:-1]
        fewer_extraction = ExtractionResult(
            raw_fees=fewer_fees,
            exchange_name="Nasdaq ISE",
            confidence=0.92,
        )
        engine = NormalizationEngine()
        fewer_schedule = engine.normalize(fewer_extraction, EXCHANGE_CODE)

        report = self.detector.detect(
            old_schedule=self.schedule,
            new_schedule=fewer_schedule,
            old_version=1,
            new_version=2,
        )
        assert report.removed_count == 1


# ---------------------------------------------------------------------------
# Step 5: Full Pipeline Integration (all steps chained)
# ---------------------------------------------------------------------------


class TestFullPipelineIntegration:
    """Chain all steps together: Parse → Extract (mock) → Normalize → Diff."""

    @patch.object(AIExtractor, "extract", return_value=MOCK_EXTRACTION_RESULT)
    def test_full_pipeline_first_run(self, mock_extract):
        # Step 1: Parse HTML
        parser = HtmlParser()
        document = parser.extract(NASDAQ_ISE_HTML)
        assert len(document.tables) >= 3

        # Step 2: AI extraction (mocked)
        extractor = AIExtractor()
        extraction = extractor.extract(document, EXCHANGE_CODE)
        assert len(extraction.raw_fees) == 28

        # Step 3: Normalize
        normalizer = NormalizationEngine()
        schedule = normalizer.normalize(extraction, EXCHANGE_CODE)
        assert schedule.exchange_code == EXCHANGE_CODE
        assert len(schedule.fees) == 28

        # Step 4: Diff (first run)
        detector = ChangeDetector()
        report = detector.detect(
            old_schedule=None,
            new_schedule=schedule,
            old_version=None,
            new_version=1,
        )
        assert report.has_changes is True
        assert report.new_count == 28
        assert report.exchange_code == EXCHANGE_CODE

    @patch.object(AIExtractor, "extract", return_value=MOCK_EXTRACTION_RESULT)
    def test_full_pipeline_second_run_with_changes(self, mock_extract):
        """Simulate two runs where the second has a fee change."""
        parser = HtmlParser()
        normalizer = NormalizationEngine()
        detector = ChangeDetector()

        # --- Run 1 ---
        doc1 = parser.extract(NASDAQ_ISE_HTML)
        extractor = AIExtractor()
        extraction1 = extractor.extract(doc1, EXCHANGE_CODE)
        schedule_v1 = normalizer.normalize(extraction1, EXCHANGE_CODE)

        # --- Run 2 (Customer penny taker increases $0.50 → $0.53) ---
        modified_fees = [f.copy() for f in MOCK_EXTRACTION_RESULT.raw_fees]
        modified_fees[6] = {**modified_fees[6], "amount": 0.53}

        mock_extract.return_value = ExtractionResult(
            raw_fees=modified_fees,
            exchange_name="Nasdaq ISE",
            effective_date="March 1, 2026",
            confidence=0.93,
        )
        extraction2 = extractor.extract(doc1, EXCHANGE_CODE)
        schedule_v2 = normalizer.normalize(extraction2, EXCHANGE_CODE)

        report = detector.detect(
            old_schedule=schedule_v1,
            new_schedule=schedule_v2,
            old_version=1,
            new_version=2,
        )
        assert report.has_changes is True
        assert report.modified_count == 1
        assert report.new_count == 0
        assert report.removed_count == 0

        change = report.changes[0]
        assert change.change_type == "MODIFIED"
        assert change.old_amount_cents == 5000  # $0.50
        assert change.new_amount_cents == 5300  # $0.53
