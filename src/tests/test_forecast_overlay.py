"""Overlay behavior tests for generate_forecasts.

Uses a stub model + a tiny two-hour weather frame to check the three
branches of the is_open precedence table from
Specs/changes/integrate-opening-hours/architecture.md#overlay-semantics.
"""

from datetime import datetime
from pathlib import Path
from zoneinfo import ZoneInfo

import pandas as pd
import pytest

from forecast.forecast import generate_forecasts
from loaders.opening_hours_loader import load_latest_snapshot

TIMEZONE = ZoneInfo("Europe/Berlin")
FIXTURE_DIR = Path(__file__).parent / "fixtures"

ALIASES = {"sauna:Nordbad Sauna": "Nordbad"}


class StubModel:
    """Always predicts 42.0% free, enough to be distinguishable from 0.0."""
    def predict(self, features):
        return [42.0]


def _weather_frame(rows):
    df = pd.DataFrame(rows)
    df["timestamp"] = pd.to_datetime(df["timestamp"])
    return df


@pytest.fixture
def schedules():
    return load_latest_snapshot(FIXTURE_DIR, ALIASES)


def test_closed_hour_emits_is_open_0_and_zero_percent(schedules):
    """Nordbad pool at 05:00 Monday → outside 07:00-22:00, expect closed."""
    weather = _weather_frame([
        {
            "timestamp": datetime(2026, 4, 20, 5, 0, tzinfo=TIMEZONE),
            "temperature_c": 10.0, "precipitation_mm": 0.0,
            "weather_code": 0, "cloud_cover_percent": 20.0,
        }
    ])
    forecasts = generate_forecasts(
        model=StubModel(),
        facility_types=[("Nordbad", "pool")],
        weather_df=weather,
        public_holidays=set(),
        school_vacations=[],
        opening_schedules=schedules,
    )
    assert len(forecasts) == 1
    assert forecasts[0]["is_open"] == 0
    assert forecasts[0]["occupancy_percent"] == 0.0


def test_open_hour_keeps_model_prediction(schedules):
    """Nordbad pool at 12:00 Monday → inside interval, expect is_open=1 and 42.0%."""
    weather = _weather_frame([
        {
            "timestamp": datetime(2026, 4, 20, 12, 0, tzinfo=TIMEZONE),
            "temperature_c": 10.0, "precipitation_mm": 0.0,
            "weather_code": 0, "cloud_cover_percent": 20.0,
        }
    ])
    forecasts = generate_forecasts(
        model=StubModel(),
        facility_types=[("Nordbad", "pool")],
        weather_df=weather,
        public_holidays=set(),
        school_vacations=[],
        opening_schedules=schedules,
    )
    assert forecasts[0]["is_open"] == 1
    assert forecasts[0]["occupancy_percent"] == 42.0


def test_unknown_facility_emits_null_and_keeps_prediction(schedules, caplog):
    weather = _weather_frame([
        {
            "timestamp": datetime(2026, 4, 20, 12, 0, tzinfo=TIMEZONE),
            "temperature_c": 10.0, "precipitation_mm": 0.0,
            "weather_code": 0, "cloud_cover_percent": 20.0,
        }
    ])
    with caplog.at_level("WARNING"):
        forecasts = generate_forecasts(
            model=StubModel(),
            facility_types=[("Ghost Facility", "pool")],
            weather_df=weather,
            public_holidays=set(),
            school_vacations=[],
            opening_schedules=schedules,
        )
    assert forecasts[0]["is_open"] == "NULL"
    assert forecasts[0]["occupancy_percent"] == 42.0
    assert any(
        "No opening hours known for pool:Ghost Facility" in r.message
        for r in caplog.records
    )


def test_unknown_warning_only_once_per_facility(schedules, caplog):
    """Same ghost facility across two hours → exactly one warning."""
    weather = _weather_frame([
        {
            "timestamp": datetime(2026, 4, 20, 10, 0, tzinfo=TIMEZONE),
            "temperature_c": 10.0, "precipitation_mm": 0.0,
            "weather_code": 0, "cloud_cover_percent": 20.0,
        },
        {
            "timestamp": datetime(2026, 4, 20, 11, 0, tzinfo=TIMEZONE),
            "temperature_c": 10.0, "precipitation_mm": 0.0,
            "weather_code": 0, "cloud_cover_percent": 20.0,
        },
    ])
    with caplog.at_level("WARNING"):
        generate_forecasts(
            model=StubModel(),
            facility_types=[("Ghost", "pool")],
            weather_df=weather,
            public_holidays=set(),
            school_vacations=[],
            opening_schedules=schedules,
        )
    warnings = [r for r in caplog.records if "Ghost" in r.message]
    assert len(warnings) == 1


def test_closed_for_season_always_closed(schedules):
    """Ice rink closed for season → every hour is_open=0."""
    weather = _weather_frame([
        {
            "timestamp": datetime(2026, 4, 20, h, 0, tzinfo=TIMEZONE),
            "temperature_c": 10.0, "precipitation_mm": 0.0,
            "weather_code": 0, "cloud_cover_percent": 20.0,
        }
        for h in (10, 14, 20)
    ])
    forecasts = generate_forecasts(
        model=StubModel(),
        facility_types=[("Prinzregentenstadion - Eislaufbahn", "ice_rink")],
        weather_df=weather,
        public_holidays=set(),
        school_vacations=[],
        opening_schedules=schedules,
    )
    assert all(f["is_open"] == 0 for f in forecasts)
    assert all(f["occupancy_percent"] == 0.0 for f in forecasts)


def test_empty_schedule_falls_back_to_null_without_warning(schedules):
    """With no snapshot loaded, forecast still works; no warnings spam."""
    weather = _weather_frame([
        {
            "timestamp": datetime(2026, 4, 20, 12, 0, tzinfo=TIMEZONE),
            "temperature_c": 10.0, "precipitation_mm": 0.0,
            "weather_code": 0, "cloud_cover_percent": 20.0,
        }
    ])
    forecasts = generate_forecasts(
        model=StubModel(),
        facility_types=[("Nordbad", "pool")],
        weather_df=weather,
        public_holidays=set(),
        school_vacations=[],
        opening_schedules={},  # no snapshot
    )
    assert forecasts[0]["is_open"] == "NULL"
    assert forecasts[0]["occupancy_percent"] == 42.0
