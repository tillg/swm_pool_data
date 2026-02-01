#!/usr/bin/env python3
"""Generate occupancy forecasts for all facilities."""

import argparse
import json
import logging
import pickle
import sys
from datetime import datetime, timedelta
from pathlib import Path
from zoneinfo import ZoneInfo

import pandas as pd

TIMEZONE = ZoneInfo("Europe/Berlin")
FORECAST_HOURS = 48

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s - %(levelname)s - %(message)s"
)
logger = logging.getLogger(__name__)


def load_model(model_path: Path):
    """Load trained model from pickle file."""
    if not model_path.exists():
        logger.error(f"Model file not found: {model_path}")
        sys.exit(1)

    with open(model_path, "rb") as f:
        model = pickle.load(f)
    logger.info(f"Loaded model from {model_path}")
    return model


def get_latest_weather_file(weather_dir: Path) -> Path:
    """Find the most recent weather JSON file."""
    weather_files = sorted(weather_dir.glob("weather_*.json"))
    if not weather_files:
        logger.error(f"No weather files found in {weather_dir}")
        sys.exit(1)
    return weather_files[-1]


def load_weather_forecast(weather_path: Path, start_time: datetime) -> pd.DataFrame:
    """Load weather forecast data for the next 48 hours."""
    with open(weather_path, "r") as f:
        data = json.load(f)

    hourly = data["hourly"]
    df = pd.DataFrame(hourly)
    df["timestamp"] = pd.to_datetime(df["timestamp"])

    # Filter to next 48 hours from start_time
    end_time = start_time + timedelta(hours=FORECAST_HOURS)
    df = df[(df["timestamp"] >= start_time) & (df["timestamp"] < end_time)]

    if len(df) < FORECAST_HOURS:
        logger.error(
            f"Weather forecast incomplete: only {len(df)} hours available, "
            f"need {FORECAST_HOURS}"
        )
        sys.exit(1)

    logger.info(f"Loaded {len(df)} hours of weather forecast")
    return df


def get_facilities(config_path: Path = None) -> dict[str, str]:
    """Get list of facilities and their types from config file.

    Args:
        config_path: Path to facility_types.json (default: ../config/facility_types.json)

    Returns:
        Dictionary mapping facility_name to facility_type
    """
    if config_path is None:
        config_path = Path(__file__).parent.parent / "config" / "facility_types.json"

    if not config_path.exists():
        logger.error(f"Facility types config not found: {config_path}")
        logger.error("Run transform.py first to generate this file")
        sys.exit(1)

    with open(config_path, "r") as f:
        facility_types = json.load(f)

    logger.info(f"Found {len(facility_types)} facilities")
    return facility_types


def load_holiday_data(holiday_dir: Path) -> tuple[set, list]:
    """Load public holidays and school vacation periods."""
    public_holidays = set()
    school_vacations = []

    # Load public holidays
    public_path = holiday_dir / "public_holidays.json"
    if public_path.exists():
        with open(public_path, "r") as f:
            data = json.load(f)
            # Extract date strings from holiday objects
            public_holidays = {h["date"] for h in data.get("holidays", [])}

    # Load school vacations
    school_path = holiday_dir / "school_holidays.json"
    if school_path.exists():
        with open(school_path, "r") as f:
            data = json.load(f)
            school_vacations = data.get("vacations", [])

    return public_holidays, school_vacations


def is_school_vacation(dt: datetime, vacations: list) -> bool:
    """Check if date falls within a school vacation period."""
    date_str = dt.strftime("%Y-%m-%d")
    for period in vacations:
        if period["start"] <= date_str <= period["end"]:
            return True
    return False


def generate_forecasts(
    model,
    facility_types: dict[str, str],
    weather_df: pd.DataFrame,
    public_holidays: set,
    school_vacations: list,
) -> list[dict]:
    """Generate occupancy predictions for all facilities and hours."""
    forecasts = []

    for _, weather_row in weather_df.iterrows():
        ts = weather_row["timestamp"]
        ts_tz = ts.tz_localize(TIMEZONE) if ts.tzinfo is None else ts

        # Compute time-based features
        hour = ts.hour
        day_of_week = ts.dayofweek
        month = ts.month
        is_weekend = 1 if ts.dayofweek >= 5 else 0
        is_holiday = 1 if ts.strftime("%Y-%m-%d") in public_holidays else 0
        is_school_vac = 1 if is_school_vacation(ts, school_vacations) else 0

        # Build features for each facility
        for facility_name, facility_type in facility_types.items():
            features = pd.DataFrame([{
                "facility": facility_name,
                "hour": hour,
                "day_of_week": day_of_week,
                "month": month,
                "is_weekend": is_weekend,
                "is_holiday": is_holiday,
                "is_school_vacation": is_school_vac,
                "temperature_c": weather_row["temperature_c"],
                "precipitation_mm": weather_row["precipitation_mm"],
                "weather_code": weather_row["weather_code"],
            }])
            features["facility"] = features["facility"].astype("category")

            prediction = model.predict(features)[0]
            # Clamp to valid range
            prediction = max(0, min(100, prediction))

            # Format timestamp as ISO 8601 with timezone
            ts_str = ts_tz.strftime("%Y-%m-%dT%H:%M:%S%z")
            # Insert colon in timezone offset for ISO 8601 compliance (+0100 -> +01:00)
            ts_str = ts_str[:-2] + ":" + ts_str[-2:]

            forecasts.append({
                "timestamp": ts_str,
                "facility_name": facility_name,
                "facility_type": facility_type,
                "occupancy_percent": round(prediction, 1),
                "is_open": "NULL",
                "hour": hour,
                "day_of_week": day_of_week,
                "month": month,
                "is_weekend": is_weekend,
                "is_holiday": is_holiday,
                "is_school_vacation": is_school_vac,
                "temperature_c": weather_row["temperature_c"],
                "precipitation_mm": weather_row["precipitation_mm"],
                "weather_code": weather_row["weather_code"],
                "cloud_cover_percent": weather_row.get("cloud_cover_percent"),
                "data_source": "forecast",
            })

    return forecasts


def save_forecasts(forecasts: list[dict], output_path: Path) -> None:
    """Save forecasts to CSV file."""
    output_path.parent.mkdir(parents=True, exist_ok=True)

    df = pd.DataFrame(forecasts)

    # Define column order to match historical format
    columns = [
        "timestamp", "facility_name", "facility_type", "occupancy_percent",
        "is_open", "hour", "day_of_week", "month", "is_weekend",
        "is_holiday", "is_school_vacation",
        "temperature_c", "precipitation_mm", "weather_code", "cloud_cover_percent",
        "data_source"
    ]
    df = df[columns]

    # Sort by timestamp, facility_name
    df = df.sort_values(["timestamp", "facility_name"])

    df.to_csv(output_path, index=False)
    logger.info(f"Saved {len(forecasts)} forecasts to {output_path}")


def main():
    parser = argparse.ArgumentParser(description="Generate occupancy forecasts")
    parser.add_argument(
        "--model",
        type=str,
        default="../../models/occupancy_model.pkl",
        help="Path to trained model"
    )
    parser.add_argument(
        "--weather-dir",
        type=str,
        default="../../weather_raw",
        help="Directory containing weather JSON files"
    )
    parser.add_argument(
        "--holiday-dir",
        type=str,
        default="../../holidays",
        help="Directory containing holiday JSON files"
    )
    parser.add_argument(
        "--output",
        type=str,
        default="../../datasets/occupancy_forecast.csv",
        help="Path to save forecast CSV"
    )

    args = parser.parse_args()

    model = load_model(Path(args.model))

    weather_file = get_latest_weather_file(Path(args.weather_dir))
    logger.info(f"Using weather file: {weather_file}")

    # Start forecast from current hour
    now = datetime.now(TIMEZONE).replace(minute=0, second=0, microsecond=0)
    weather_df = load_weather_forecast(weather_file, now)

    facility_types = get_facilities()
    public_holidays, school_vacations = load_holiday_data(Path(args.holiday_dir))

    forecasts = generate_forecasts(
        model, facility_types, weather_df, public_holidays, school_vacations
    )

    save_forecasts(forecasts, Path(args.output))
    logger.info("Forecast generation complete")


if __name__ == "__main__":
    main()
