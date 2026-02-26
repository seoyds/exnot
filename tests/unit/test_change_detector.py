"""Tests for the change detection engine."""


from exnot.differ.detector import ChangeDetector


class TestChangeDetector:
    def setup_method(self):
        self.detector = ChangeDetector()

    def test_first_version_all_new(self, sample_schedule):
        """First version should report all fees as NEW."""
        report = self.detector.detect(None, sample_schedule, old_version=None, new_version=1)

        assert report.has_changes
        assert report.new_count == len(sample_schedule.fees)
        assert report.modified_count == 0
        assert report.removed_count == 0
        assert "Initial fee schedule" in report.summary

    def test_no_changes(self, sample_schedule):
        """Same schedule should report no changes."""
        report = self.detector.detect(sample_schedule, sample_schedule, old_version=1, new_version=2)

        assert not report.has_changes
        assert report.new_count == 0
        assert report.modified_count == 0
        assert report.removed_count == 0
        assert "No fee changes" in report.summary

    def test_modified_fees(self, sample_schedule, sample_schedule_updated):
        """Should detect modified fee amounts."""
        report = self.detector.detect(
            sample_schedule, sample_schedule_updated, old_version=1, new_version=2
        )

        assert report.has_changes
        modified = [c for c in report.changes if c.change_type == "MODIFIED"]
        assert len(modified) == 2  # Customer penny maker and MM penny taker

        # Check customer maker change
        customer_maker = next(
            (c for c in modified if c.participant_type == "CUSTOMER" and c.fee_type == "MAKER"),
            None,
        )
        assert customer_maker is not None
        assert customer_maker.old_amount_cents == -2500
        assert customer_maker.new_amount_cents == -2800

    def test_new_fees(self, sample_schedule, sample_schedule_updated):
        """Should detect newly added fees."""
        report = self.detector.detect(
            sample_schedule, sample_schedule_updated, old_version=1, new_version=2
        )

        new_fees = [c for c in report.changes if c.change_type == "NEW"]
        assert len(new_fees) == 1
        assert new_fees[0].fee_type == "TAKER"
        assert new_fees[0].participant_type == "CUSTOMER"

    def test_removed_fees(self, sample_schedule, sample_schedule_updated):
        """The updated schedule doesn't remove any fees in our fixture, verify 0 removed."""
        report = self.detector.detect(
            sample_schedule, sample_schedule_updated, old_version=1, new_version=2
        )

        removed = [c for c in report.changes if c.change_type == "REMOVED"]
        assert len(removed) == 0

    def test_summary_format(self, sample_schedule, sample_schedule_updated):
        """Summary should list counts of each change type."""
        report = self.detector.detect(
            sample_schedule, sample_schedule_updated, old_version=1, new_version=2
        )

        assert "modified" in report.summary
        assert "new" in report.summary


class TestChangeDetectorEdgeCases:
    def setup_method(self):
        self.detector = ChangeDetector()

    def test_both_none(self):
        """Both schedules None should not crash."""
        from exnot.normalizer.schema import NormalizedFeeSchedule

        empty = NormalizedFeeSchedule(exchange_code="TEST", exchange_name="Test")
        report = self.detector.detect(None, empty)
        assert report.new_count == 0
