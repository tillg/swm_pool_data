#!/usr/bin/env python3
"""Weather data loader for Munich using Open-Meteo API."""

import argparse
import json
import logging
import sys
import time
from datetime import datetime
from pathlib import Path
from zoneinfo import ZoneInfo

import requests

TIMEZONE = ZoneInfo("Europe/Berlin")

# Munich city center coordinates
LATITUDE = 48.1351
LONGITUDE = 11.5820

# Open-Meteo API endpoint
API_URL = "https://api.open-meteo.com/v1/forecast"

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s - %(levelname)s - %(message)s"
)
logger = logging.getLogger(__name__)


def fetch_weather(past_days: int = 7, forecast_days: int = 7) -> dict:
    """Fetch weather data from Open-Meteo API.

    Args:
        past_days: Number of historical days to fetch (max 92)
        forecast_days: Number of forecast days to fetch (max 16)

    Returns:
        Normalized weather data dictionary
    """
    params = {
        "latitude": LATITUDE,
        "longitude": LONGITUDE,
        "hourly": "temperature_2m,precipitation,weather_code,cloud_cover",
        "timezone": "Europe/Berlin",
        "past_days": past_days,
        "forecast_days": forecast_days,
    }

    max_retries = 3
    for attempt in range(max_retries):
        try:
            response = requests.get(API_URL, params=params, timeout=30)
            response.raise_for_status()
            data = response.json()
            return _normalize_response(data)
        except requests.RequestException as e:
            wait_time = 2 ** attempt  # 1s, 2s, 4s
            logger.warning(f"Attempt {attempt + 1} failed: {e}. Retrying in {wait_time}s...")
            if attempt < max_retries - 1:
                time.sleep(wait_time)
            else:
                logger.error(f"All {max_retries} attempts failed")
                raise


def _normalize_response(data: dict) -> dict:
    """Convert Open-Meteo response to our schema."""
    hourly = data.get("hourly", {})
    timestamps = hourly.get("time", [])
    temperatures = hourly.get("temperature_2m", [])
    precipitations = hourly.get("precipitation", [])
    weather_codes = hourly.get("weather_code", [])
    cloud_covers = hourly.get("cloud_cover", [])

    hourly_records = []
    for i, ts in enumerate(timestamps):
        hourly_records.append({
            "timestamp": ts + ":00+01:00" if "+" not in ts else ts,
            "temperature_c": temperatures[i] if i < len(temperatures) else None,
            "precipitation_mm": precipitations[i] if i < len(precipitations) else None,
            "weather_code": weather_codes[i] if i < len(weather_codes) else None,
            "cloud_cover_percent": cloud_covers[i] if i < len(cloud_covers) else None,
        })

    return {
        "fetched_at": datetime.now(TIMEZONE).isoformat(),
        "location": {
            "latitude": LATITUDE,
            "longitude": LONGITUDE,
            "city": "Munich"
        },
        "hourly": hourly_records
    }


def save_weather(data: dict, output_dir: Path) -> Path:
    """Save weather data to JSON file.

    Args:
        data: Weather data dictionary
        output_dir: Directory to save the file

    Returns:
        Path to the saved file
    """
    output_dir = Path(output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)

    today = datetime.now(TIMEZONE).strftime("%Y%m%d")
    filename = f"weather_{today}.json"
    filepath = output_dir / filename

    with open(filepath, "w", encoding="utf-8") as f:
        json.dump(data, f, indent=2, ensure_ascii=False)

    logger.info(f"Saved weather data to {filepath}")
    return filepath


def main():
    parser = argparse.ArgumentParser(description="Fetch weather data from Open-Meteo")
    parser.add_argument(
        "--output-dir",
        type=str,
        default="weather_raw",
        help="Output directory for weather JSON files"
    )
    parser.add_argument(
        "--past-days",
        type=int,
        default=7,
        help="Number of historical days to fetch"
    )
    parser.add_argument(
        "--forecast-days",
        type=int,
        default=7,
        help="Number of forecast days to fetch"
    )

    args = parser.parse_args()

    try:
        logger.info("Fetching weather data from Open-Meteo...")
        data = fetch_weather(past_days=args.past_days, forecast_days=args.forecast_days)
        logger.info(f"Fetched {len(data['hourly'])} hourly records")

        filepath = save_weather(data, Path(args.output_dir))
        logger.info(f"Weather data saved to {filepath}")

    except Exception as e:
        logger.error(f"Failed to fetch weather data: {e}")
        # Exit with 0 to not fail the workflow - weather data will be missing
        sys.exit(0)


if __name__ == "__main__":
    main()
