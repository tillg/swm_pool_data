"""Tests for opening_hours_loader."""

from datetime import datetime
from pathlib import Path

import pytest

from loaders.opening_hours_loader import (
    is_facility_open,
    load_latest_snapshot,
)

FIXTURE_DIR = Path(__file__).parent / "fixtures"

ALIASES = {
    "sauna:Nordbad Sauna": "Nordbad",
}


@pytest.fixture
def schedules():
    return load_latest_snapshot(FIXTURE_DIR, ALIASES)


class TestLoadLatestSnapshot:
    def test_keys_are_composite(self, schedules):
        assert ("pool", "Bad Giesing-Harlaching") in schedules
        assert ("pool", "Nordbad") in schedules
        assert ("sauna", "Nordbad") in schedules  # alias resolved
        assert ("ice_rink", "Prinzregentenstadion - Eislaufbahn") in schedules

    def test_alias_resolution_strips_legacy_name(self, schedules):
        # "Nordbad Sauna" (legacy) must be resolved to "Nordbad" (canonical)
        assert ("sauna", "Nordbad Sauna") not in schedules
        assert ("sauna", "Nordbad") in schedules

    def test_missing_directory_returns_empty(self, tmp_path, caplog):
        with caplog.at_level("WARNING"):
            result = load_latest_snapshot(tmp_path / "does-not-exist", ALIASES)
        assert result == {}
        assert any("not found" in r.message for r in caplog.records)

    def test_empty_directory_returns_empty(self, tmp_path, caplog):
        with caplog.at_level("WARNING"):
            result = load_latest_snapshot(tmp_path, ALIASES)
        assert result == {}
        assert any("No facility_opening_" in r.message for r in caplog.records)

    def test_malformed_json_returns_empty(self, tmp_path, caplog):
        (tmp_path / "facility_opening_20260420_040000.json").write_text("not json")
        with caplog.at_level("WARNING"):
            result = load_latest_snapshot(tmp_path, ALIASES)
        assert result == {}


class TestIsFacilityOpen:
    def test_hour_inside_interval_is_open(self, schedules):
        # Nordbad pool, Monday 10:00 → open 07:00-22:00
        dt = datetime(2026, 4, 20, 10, 0)  # Monday
        assert is_facility_open(schedules, "pool", "Nordbad", dt) is True

    def test_closing_hour_is_closed_half_open(self, schedules):
        # Nordbad pool, Monday 22:00 → close_time exactly
        dt = datetime(2026, 4, 20, 22, 0)
        assert is_facility_open(schedules, "pool", "Nordbad", dt) is False

    def test_just_before_close_is_open(self, schedules):
        # One minute before close
        dt = datetime(2026, 4, 20, 21, 59)
        assert is_facility_open(schedules, "pool", "Nordbad", dt) is True

    def test_before_open_is_closed(self, schedules):
        dt = datetime(2026, 4, 20, 5, 0)
        assert is_facility_open(schedules, "pool", "Nordbad", dt) is False

    def test_multi_interval_midday_gap_is_closed(self, schedules):
        # Bad Giesing-Harlaching pool Tuesday 13:00 — between two intervals
        dt = datetime(2026, 4, 21, 13, 0)  # Tuesday
        assert is_facility_open(
            schedules, "pool", "Bad Giesing-Harlaching", dt
        ) is False

    def test_multi_interval_second_interval_is_open(self, schedules):
        # Tuesday 18:00 — falls into the 15:00-21:00 second interval
        dt = datetime(2026, 4, 21, 18, 0)
        assert is_facility_open(
            schedules, "pool", "Bad Giesing-Harlaching", dt
        ) is True

    def test_closed_for_season_always_false(self, schedules):
        # Any weekday, any hour → False
        for day in range(21, 28):  # A full week in April 2026
            dt = datetime(2026, 4, day, 14, 0)
            assert is_facility_open(
                schedules, "ice_rink", "Prinzregentenstadion - Eislaufbahn", dt
            ) is False, f"Expected False for day {day}"

    def test_unknown_facility_returns_none(self, schedules):
        dt = datetime(2026, 4, 20, 10, 0)
        assert is_facility_open(schedules, "pool", "Does Not Exist", dt) is None

    def test_alias_resolved_caller_queries_canonical(self, schedules):
        # The snapshot contained "Nordbad Sauna"; after load_latest_snapshot
        # applies alias resolution, the caller queries with canonical name.
        dt = datetime(2026, 4, 20, 12, 0)  # Monday
        assert is_facility_open(schedules, "sauna", "Nordbad", dt) is True
        # Legacy name is not a valid key
        assert is_facility_open(schedules, "sauna", "Nordbad Sauna", dt) is None
