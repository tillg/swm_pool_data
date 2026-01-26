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


def get_facilities(data_path: Path) -> list[str]:
    """Get list of facilities from training data."""
    df = pd.read_csv(data_path, usecols=["pool_name"])
    facilities = df["pool_name"].unique().tolist()
    logger.info(f"Found {len(facilities)} facilities")
    return facilities


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
    facilities: list[str],
    weather_df: pd.DataFrame,
    public_holidays: set,
    school_vacations: list,
) -> list[dict]:
    """Generate occupancy predictions for all facilities and hours."""
    forecasts = []

    for _, weather_row in weather_df.iterrows():
        ts = weather_row["timestamp"]
        ts_tz = ts.tz_localize(TIMEZONE) if ts.tzinfo is None else ts

        # Build features for each facility
        for facility in facilities:
            features = pd.DataFrame([{
                "facility": facility,
                "hour": ts.hour,
                "day_of_week": ts.dayofweek,
                "month": ts.month,
                "is_weekend": 1 if ts.dayofweek >= 5 else 0,
                "is_holiday": 1 if ts.strftime("%Y-%m-%d") in public_holidays else 0,
                "is_school_vacation": 1 if is_school_vacation(ts, school_vacations) else 0,
                "temperature_c": weather_row["temperature_c"],
                "precipitation_mm": weather_row["precipitation_mm"],
                "weather_code": weather_row["weather_code"],
            }])
            features["facility"] = features["facility"].astype("category")

            prediction = model.predict(features)[0]
            # Clamp to valid range
            prediction = max(0, min(100, prediction))

            forecasts.append({
                "facility": facility,
                "timestamp": ts_tz.isoformat(),
                "predicted_occupancy": round(prediction, 1),
            })

    return forecasts


def save_forecasts(forecasts: list[dict], output_path: Path) -> None:
    """Save forecasts to JSON file."""
    output_path.parent.mkdir(parents=True, exist_ok=True)

    output = {
        "generated_at": datetime.now(TIMEZONE).isoformat(),
        "forecasts": forecasts,
    }

    with open(output_path, "w") as f:
        json.dump(output, f, indent=2)

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
        "--data",
        type=str,
        default="../../datasets/occupancy_features.csv",
        help="Path to training data (for facility list)"
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
        default="../../forecasts/forecast_latest.json",
        help="Path to save forecast JSON"
    )

    args = parser.parse_args()

    model = load_model(Path(args.model))

    weather_file = get_latest_weather_file(Path(args.weather_dir))
    logger.info(f"Using weather file: {weather_file}")

    # Start forecast from current hour
    now = datetime.now(TIMEZONE).replace(minute=0, second=0, microsecond=0)
    weather_df = load_weather_forecast(weather_file, now)

    facilities = get_facilities(Path(args.data))
    public_holidays, school_vacations = load_holiday_data(Path(args.holiday_dir))

    forecasts = generate_forecasts(
        model, facilities, weather_df, public_holidays, school_vacations
    )

    save_forecasts(forecasts, Path(args.output))
    logger.info("Forecast generation complete")


if __name__ == "__main__":
    main()
