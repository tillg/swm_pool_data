"""Tests for transform module."""

from datetime import datetime
from pathlib import Path

import pandas as pd
import pytest

from loaders.opening_hours_loader import load_latest_snapshot
from transform import apply_opening_hours_overlay, resolve_facility_alias

FIXTURE_DIR = Path(__file__).parent / "fixtures"


class TestResolveFacilityAlias:
    """Tests for resolve_facility_alias function."""

    def test_alias_match(self):
        """Should return canonical name when alias exists."""
        aliases = {
            "sauna:Dantebad Sauna": "Dantebad",
            "sauna:Nordbad Sauna": "Nordbad",
        }
        result = resolve_facility_alias("Dantebad Sauna", "sauna", aliases)
        assert result == "Dantebad"

    def test_no_match_passthrough(self):
        """Should return original name when no alias exists."""
        aliases = {
            "sauna:Dantebad Sauna": "Dantebad",
        }
        result = resolve_facility_alias("Müller'sches Volksbad", "sauna", aliases)
        assert result == "Müller'sches Volksbad"

    def test_type_aware_lookup(self):
        """Should only match when facility type matches."""
        aliases = {
            "sauna:Nordbad Sauna": "Nordbad",
        }
        # Pool should not match sauna alias
        result = resolve_facility_alias("Nordbad Sauna", "pool", aliases)
        assert result == "Nordbad Sauna"

    def test_empty_aliases(self):
        """Should return original name with empty aliases dict."""
        result = resolve_facility_alias("Dantebad Sauna", "sauna", {})
        assert result == "Dantebad Sauna"


class TestApplyOpeningHoursOverlay:
    """Tests for apply_opening_hours_overlay function."""

    @pytest.fixture
    def schedules(self):
        return load_latest_snapshot(FIXTURE_DIR, aliases={"sauna:Nordbad Sauna": "Nordbad"})

    def _frame(self, rows):
        df = pd.DataFrame(rows)
        df["timestamp"] = pd.to_datetime(df["timestamp"])
        return df

    def test_closed_hour_zeros_out(self, schedules):
        """Row inside a closed time band → is_open=0, occupancy_percent=0."""
        # Nordbad pool fixture: 07:00-22:00 daily; row at 03:00 is closed.
        df = self._frame([{
            "timestamp": datetime(2026, 4, 25, 3, 30),  # Saturday 03:30
            "facility_name": "Nordbad",
            "facility_type": "pool",
            "occupancy_percent": 100.0,
            "is_open": 1,
        }])
        result = apply_opening_hours_overlay(df, schedules)
        assert result.iloc[0]["is_open"] == 0
        assert result.iloc[0]["occupancy_percent"] == 0.0

    def test_open_hour_keeps_observation(self, schedules):
        """Row inside an open band → is_open=1, occupancy_percent untouched."""
        df = self._frame([{
            "timestamp": datetime(2026, 4, 25, 12, 30),  # Saturday lunchtime
            "facility_name": "Nordbad",
            "facility_type": "pool",
            "occupancy_percent": 65.0,
            "is_open": 1,
        }])
        result = apply_opening_hours_overlay(df, schedules)
        assert result.iloc[0]["is_open"] == 1
        assert result.iloc[0]["occupancy_percent"] == 65.0

    def test_closed_for_season_zeros_out_every_hour(self, schedules):
        """Ice rink with closed_for_season → is_open=0 for every hour."""
        df = self._frame([
            {
                "timestamp": datetime(2026, 4, 25, h, 0),
                "facility_name": "Prinzregentenstadion - Eislaufbahn",
                "facility_type": "ice_rink",
                "occupancy_percent": 100.0,
                "is_open": 1,
            }
            for h in (10, 14, 20)
        ])
        result = apply_opening_hours_overlay(df, schedules)
        assert (result["is_open"] == 0).all()
        assert (result["occupancy_percent"] == 0.0).all()

    def test_unknown_facility_left_untouched(self, schedules):
        """Facility missing from snapshot → row unchanged."""
        df = self._frame([{
            "timestamp": datetime(2026, 4, 25, 3, 30),
            "facility_name": "Ghost Facility",
            "facility_type": "pool",
            "occupancy_percent": 42.0,
            "is_open": 1,
        }])
        result = apply_opening_hours_overlay(df, schedules)
        # Untouched: original is_open=1 stays
        assert result.iloc[0]["is_open"] == 1
        assert result.iloc[0]["occupancy_percent"] == 42.0

    def test_alias_resolved_canonical_name_lookup(self, schedules):
        """Snapshot has 'Nordbad Sauna' (legacy); rows use 'Nordbad' canonical."""
        df = self._frame([{
            "timestamp": datetime(2026, 4, 25, 3, 30),  # Closed: sauna opens 09:00 Saturday
            "facility_name": "Nordbad",
            "facility_type": "sauna",
            "occupancy_percent": 100.0,
            "is_open": 1,
        }])
        result = apply_opening_hours_overlay(df, schedules)
        assert result.iloc[0]["is_open"] == 0
        assert result.iloc[0]["occupancy_percent"] == 0.0

    def test_idempotent(self, schedules):
        """Applying overlay twice yields the same result as once."""
        df = self._frame([
            {
                "timestamp": datetime(2026, 4, 25, 3, 30),
                "facility_name": "Nordbad", "facility_type": "pool",
                "occupancy_percent": 100.0, "is_open": 1,
            },
            {
                "timestamp": datetime(2026, 4, 25, 12, 30),
                "facility_name": "Nordbad", "facility_type": "pool",
                "occupancy_percent": 65.0, "is_open": 1,
            },
        ])
        once = apply_opening_hours_overlay(df.copy(), schedules)
        twice = apply_opening_hours_overlay(once.copy(), schedules)
        pd.testing.assert_frame_equal(once, twice)

    def test_empty_schedules_passthrough(self):
        """No snapshot → frame returned unchanged."""
        df = self._frame([{
            "timestamp": datetime(2026, 4, 25, 3, 30),
            "facility_name": "Nordbad", "facility_type": "pool",
            "occupancy_percent": 100.0, "is_open": 1,
        }])
        result = apply_opening_hours_overlay(df, schedules={})
        assert result.iloc[0]["is_open"] == 1
        assert result.iloc[0]["occupancy_percent"] == 100.0
