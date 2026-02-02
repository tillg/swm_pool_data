"""Tests for data irregularity checks."""

from datetime import datetime, timedelta

import pandas as pd
import pytest

from checks.check_raw_scrapes import (
    check_capacity_changes,
    check_missing_facilities,
    check_new_facilities,
    check_scrape_gaps,
    extract_facilities_from_scrape,
    parse_capacity,
)
from checks.check_compiled_data import (
    check_extended_zero_occupancy,
    check_invalid_occupancy,
    check_missing_facility_types,
    check_new_facility_types,
)


class TestParseCapacity:
    """Tests for parse_capacity function."""

    def test_standard_format(self):
        """Should parse standard format."""
        assert parse_capacity("57/311 persons") == 311

    def test_singular_person(self):
        """Should parse singular 'person'."""
        assert parse_capacity("1/100 person") == 100

    def test_none_input(self):
        """Should return None for None input."""
        assert parse_capacity(None) is None

    def test_empty_string(self):
        """Should return None for empty string."""
        assert parse_capacity("") is None

    def test_invalid_format(self):
        """Should return None for invalid format."""
        assert parse_capacity("not a capacity") is None


class TestExtractFacilitiesFromScrape:
    """Tests for extract_facilities_from_scrape function."""

    def test_extracts_pools_and_saunas(self):
        """Should extract both pools and saunas."""
        data = {
            "scrape_timestamp": "2026-01-17T10:00:00+01:00",
            "pools": [
                {
                    "pool_name": "Nordbad",
                    "facility_type": "pool",
                    "raw_occupancy": "50/177 persons",
                    "timestamp": "2026-01-17T10:00:00+01:00",
                }
            ],
            "saunas": [
                {
                    "pool_name": "Nordbad Sauna",
                    "facility_type": "sauna",
                    "raw_occupancy": "10/146 persons",
                    "timestamp": "2026-01-17T10:00:00+01:00",
                }
            ],
        }
        facilities = extract_facilities_from_scrape(data)
        assert len(facilities) == 2
        assert facilities[0]["name"] == "Nordbad"
        assert facilities[0]["type"] == "pool"
        assert facilities[0]["capacity"] == 177
        assert facilities[1]["name"] == "Nordbad Sauna"
        assert facilities[1]["type"] == "sauna"
        assert facilities[1]["capacity"] == 146


class TestCheckMissingFacilities:
    """Tests for check_missing_facilities function."""

    def test_no_missing_facilities(self):
        """Should return empty list when all facilities present."""
        historical = {("pool", "Nordbad"), ("sauna", "Nordbad Sauna")}
        scrapes = [
            {
                "_parsed_timestamp": datetime(2026, 1, 17, 10, 0),
                "pools": [{"pool_name": "Nordbad", "facility_type": "pool"}],
                "saunas": [{"pool_name": "Nordbad Sauna", "facility_type": "sauna"}],
            }
        ] * 10  # 10 scrapes to meet threshold
        # Set timestamps spread over 2+ hours
        for i, s in enumerate(scrapes):
            s["_parsed_timestamp"] = datetime(2026, 1, 17, 10, 0) + timedelta(minutes=15 * i)

        issues = check_missing_facilities(scrapes, historical)
        assert issues == []

    def test_detects_missing_facility(self):
        """Should detect missing facility after threshold."""
        historical = {("pool", "Nordbad"), ("pool", "Westbad")}
        scrapes = []
        for i in range(10):
            scrapes.append({
                "_parsed_timestamp": datetime(2026, 1, 17, 10, 0) + timedelta(minutes=15 * i),
                "pools": [{"pool_name": "Nordbad", "facility_type": "pool"}],
            })

        issues = check_missing_facilities(scrapes, historical)
        assert len(issues) == 1
        assert "pool:Westbad" in issues[0]


class TestCheckNewFacilities:
    """Tests for check_new_facilities function."""

    def test_detects_new_facility(self):
        """Should detect new facility not in historical data."""
        historical = {("pool", "Nordbad")}
        scrapes = [
            {
                "pools": [
                    {"pool_name": "Nordbad", "facility_type": "pool"},
                    {"pool_name": "Westbad", "facility_type": "pool"},
                ],
            }
        ]

        issues = check_new_facilities(scrapes, historical)
        assert len(issues) == 1
        assert "pool:Westbad" in issues[0]

    def test_no_new_facilities(self):
        """Should return empty list when no new facilities."""
        historical = {("pool", "Nordbad"), ("pool", "Westbad")}
        scrapes = [
            {
                "pools": [
                    {"pool_name": "Nordbad", "facility_type": "pool"},
                ],
            }
        ]

        issues = check_new_facilities(scrapes, historical)
        assert issues == []


class TestCheckCapacityChanges:
    """Tests for check_capacity_changes function."""

    def test_detects_capacity_change(self):
        """Should detect capacity change."""
        historical = {("pool", "Nordbad"): 177}
        scrapes = [
            {
                "pools": [
                    {
                        "pool_name": "Nordbad",
                        "facility_type": "pool",
                        "raw_occupancy": "50/200 persons",
                    }
                ],
            }
        ]

        issues = check_capacity_changes(scrapes, historical)
        assert len(issues) == 1
        assert "177" in issues[0] and "200" in issues[0]

    def test_no_change(self):
        """Should return empty list when capacity unchanged."""
        historical = {("pool", "Nordbad"): 177}
        scrapes = [
            {
                "pools": [
                    {
                        "pool_name": "Nordbad",
                        "facility_type": "pool",
                        "raw_occupancy": "50/177 persons",
                    }
                ],
            }
        ]

        issues = check_capacity_changes(scrapes, historical)
        assert issues == []


class TestCheckScrapeGaps:
    """Tests for check_scrape_gaps function."""

    def test_detects_gap(self, tmp_path):
        """Should detect gap of 2+ hours."""
        import json

        # Create scrapes with a gap
        scrape1 = {
            "scrape_timestamp": "2026-01-17T10:00:00+01:00",
            "pools": [],
        }
        scrape2 = {
            "scrape_timestamp": "2026-01-17T13:00:00+01:00",  # 3 hour gap
            "pools": [],
        }

        (tmp_path / "pool_data_20260117_100000.json").write_text(json.dumps(scrape1))
        (tmp_path / "pool_data_20260117_130000.json").write_text(json.dumps(scrape2))

        issues = check_scrape_gaps(tmp_path, datetime(2026, 1, 17))
        assert len(issues) == 1
        assert "gap" in issues[0].lower()


class TestCheckNewFacilityTypes:
    """Tests for check_new_facility_types function."""

    def test_detects_new_type(self):
        """Should detect new facility type."""
        df = pd.DataFrame({
            "timestamp": [datetime.now() - timedelta(hours=1)],
            "facility_type": ["ice_rink"],
            "facility_name": ["Test"],
        })
        historical = {"pool", "sauna"}

        issues = check_new_facility_types(df, historical)
        assert len(issues) == 1
        assert "ice_rink" in issues[0]


class TestCheckMissingFacilityTypes:
    """Tests for check_missing_facility_types function."""

    def test_detects_missing_type(self):
        """Should detect missing facility type."""
        df = pd.DataFrame({
            "timestamp": [datetime.now() - timedelta(hours=1)],
            "facility_type": ["pool"],
            "facility_name": ["Test"],
        })
        historical = {"pool", "sauna"}

        issues = check_missing_facility_types(df, historical)
        assert len(issues) == 1
        assert "sauna" in issues[0]


class TestCheckInvalidOccupancy:
    """Tests for check_invalid_occupancy function."""

    def test_detects_over_100(self):
        """Should detect occupancy over 100%."""
        df = pd.DataFrame({
            "timestamp": [datetime.now() - timedelta(hours=1)],
            "facility_type": ["pool"],
            "facility_name": ["Nordbad"],
            "occupancy_percent": [150.0],
        })

        issues = check_invalid_occupancy(df)
        assert len(issues) == 1
        assert "150" in issues[0]

    def test_ignores_valid(self):
        """Should not flag valid occupancy."""
        df = pd.DataFrame({
            "timestamp": [datetime.now() - timedelta(hours=1)],
            "facility_type": ["pool"],
            "facility_name": ["Nordbad"],
            "occupancy_percent": [85.0],
        })

        issues = check_invalid_occupancy(df)
        assert issues == []


class TestCheckExtendedZeroOccupancy:
    """Tests for check_extended_zero_occupancy function."""

    def test_detects_extended_zero_daytime(self):
        """Should detect extended zero during daytime."""
        now = datetime.now()
        # Create data with 0% for 10 hours during daytime
        timestamps = [now - timedelta(hours=i) for i in range(10)]
        df = pd.DataFrame({
            "timestamp": timestamps,
            "facility_type": ["pool"] * 10,
            "facility_name": ["Nordbad"] * 10,
            "occupancy_percent": [0.0] * 10,
            "hour": [12] * 10,  # All during daytime
        })

        issues = check_extended_zero_occupancy(df, threshold_hours=8)
        assert len(issues) == 1
        assert "Nordbad" in issues[0]

    def test_ignores_nighttime_zeros(self):
        """Should ignore zeros during nighttime."""
        now = datetime.now()
        timestamps = [now - timedelta(hours=i) for i in range(10)]
        df = pd.DataFrame({
            "timestamp": timestamps,
            "facility_type": ["pool"] * 10,
            "facility_name": ["Nordbad"] * 10,
            "occupancy_percent": [0.0] * 10,
            "hour": [3] * 10,  # All during nighttime
        })

        issues = check_extended_zero_occupancy(df, threshold_hours=8)
        assert issues == []

    def test_ignores_short_zeros(self):
        """Should ignore zeros shorter than threshold."""
        now = datetime.now()
        timestamps = [now - timedelta(hours=i) for i in range(5)]
        df = pd.DataFrame({
            "timestamp": timestamps,
            "facility_type": ["pool"] * 5,
            "facility_name": ["Nordbad"] * 5,
            "occupancy_percent": [0.0] * 5,
            "hour": [12] * 5,  # Daytime but only 5 hours
        })

        issues = check_extended_zero_occupancy(df, threshold_hours=8)
        assert issues == []
