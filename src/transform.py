#!/usr/bin/env python3
"""Data transformation pipeline for pool occupancy with weather and holiday features."""

import argparse
import json
import logging
import sys
from datetime import datetime
from pathlib import Path
from zoneinfo import ZoneInfo

import pandas as pd

from loaders.holiday_loader import (
    is_public_holiday,
    is_school_vacation,
    load_public_holidays,
    load_school_holidays,
)

TIMEZONE = ZoneInfo("Europe/Berlin")

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s - %(levelname)s - %(message)s"
)
logger = logging.getLogger(__name__)


def load_facility_aliases(config_dir: Path) -> dict:
    """Load facility alias mapping from JSON file.

    Args:
        config_dir: Directory containing facility_aliases.json

    Returns:
        Dictionary mapping "{facility_type}:{old_name}" to canonical name
    """
    aliases_path = config_dir / "facility_aliases.json"
    if not aliases_path.exists():
        raise FileNotFoundError(f"Facility aliases file not found: {aliases_path}")
    with open(aliases_path, encoding="utf-8") as f:
        return json.load(f)


def resolve_facility_alias(facility_name: str, facility_type: str, aliases: dict) -> str:
    """Resolve facility name using type-aware alias mapping.

    Args:
        facility_name: Original facility name from raw data
        facility_type: Facility type (pool, sauna, etc.)
        aliases: Dictionary mapping "{type}:{old_name}" to canonical name

    Returns:
        Canonical facility name (or original if no alias exists)
    """
    key = f"{facility_type}:{facility_name}"
    return aliases.get(key, facility_name)


def load_pool_data(input_dir: Path, since: datetime = None, aliases: dict = None) -> pd.DataFrame:
    """Load pool JSON files into a DataFrame.

    Args:
        input_dir: Directory containing pool_data_*.json files
        since: Optional datetime to filter files (only load files after this date)
        aliases: Optional dict mapping "{type}:{old_name}" to canonical name

    Returns:
        DataFrame with pool occupancy records
    """
    if aliases is None:
        aliases = {}
    input_dir = Path(input_dir)
    json_files = sorted(input_dir.glob("pool_data_*.json"))

    if not json_files:
        logger.warning(f"No pool data files found in {input_dir}")
        return pd.DataFrame()

    records = []
    for filepath in json_files:
        try:
            with open(filepath, encoding="utf-8") as f:
                data = json.load(f)

            # Extract timestamp from file for filtering
            scrape_ts = data.get("scrape_timestamp")
            if since and scrape_ts:
                file_dt = datetime.fromisoformat(scrape_ts.replace("Z", "+00:00"))
                if file_dt.replace(tzinfo=None) < since.replace(tzinfo=None):
                    continue

            # Process all facility types (pools, saunas, ice_rinks, etc.)
            # Dynamically find all keys containing facility data (lists of dicts with facility_type)
            for key, value in data.items():
                if not isinstance(value, list) or not value:
                    continue
                # Check if this looks like facility data (first item has facility_type)
                if isinstance(value[0], dict) and "facility_type" in value[0]:
                    for facility in value:
                        raw_name = facility.get("pool_name")
                        fac_type = facility.get("facility_type")
                        canonical_name = resolve_facility_alias(raw_name, fac_type, aliases)
                        records.append({
                            "timestamp": facility.get("timestamp"),
                            "facility_name": canonical_name,
                            "facility_type": fac_type,
                            "occupancy_percent": facility.get("occupancy_percent"),
                            "is_open": 1 if facility.get("is_open") else 0,
                            "hour": facility.get("hour"),
                            "day_of_week": facility.get("day_of_week"),
                            "is_weekend": 1 if facility.get("is_weekend") else 0,
                        })

        except (json.JSONDecodeError, KeyError) as e:
            logger.warning(f"Skipping invalid file {filepath}: {e}")
            continue

    if not records:
        return pd.DataFrame()

    df = pd.DataFrame(records)
    df["timestamp"] = pd.to_datetime(df["timestamp"])
    # Make timezone-naive for consistent matching with weather data
    if df["timestamp"].dt.tz is not None:
        df["timestamp"] = df["timestamp"].dt.tz_localize(None)
    return df


def load_weather_data(input_dir: Path) -> pd.DataFrame:
    """Load and combine weather JSON files into hourly DataFrame.

    Args:
        input_dir: Directory containing weather_*.json files

    Returns:
        DataFrame indexed by hour timestamp with weather columns
    """
    input_dir = Path(input_dir)
    json_files = sorted(input_dir.glob("weather_*.json"))

    if not json_files:
        logger.warning(f"No weather files found in {input_dir}")
        return pd.DataFrame()

    records = []
    for filepath in json_files:
        try:
            with open(filepath, encoding="utf-8") as f:
                data = json.load(f)

            for hour_data in data.get("hourly", []):
                records.append({
                    "weather_hour": hour_data.get("timestamp"),
                    "temperature_c": hour_data.get("temperature_c"),
                    "precipitation_mm": hour_data.get("precipitation_mm"),
                    "weather_code": hour_data.get("weather_code"),
                    "cloud_cover_percent": hour_data.get("cloud_cover_percent"),
                })

        except (json.JSONDecodeError, KeyError) as e:
            logger.warning(f"Skipping invalid weather file {filepath}: {e}")
            continue

    if not records:
        return pd.DataFrame()

    df = pd.DataFrame(records)
    df["weather_hour"] = pd.to_datetime(df["weather_hour"], utc=True)
    # Convert to Berlin time and make timezone-naive for easier matching
    df["weather_hour"] = df["weather_hour"].dt.tz_convert("Europe/Berlin").dt.tz_localize(None)
    # Remove duplicates, keeping the most recent data
    df = df.drop_duplicates(subset=["weather_hour"], keep="last")
    df = df.set_index("weather_hour").sort_index()
    return df


def align_weather(pool_timestamp, weather_df: pd.DataFrame) -> dict:
    """Get weather data for the hour containing pool_timestamp.

    Args:
        pool_timestamp: Pool record timestamp (datetime or pandas Timestamp)
        weather_df: Weather DataFrame indexed by hour

    Returns:
        Dictionary with weather columns, or empty dict if not found
    """
    if weather_df.empty:
        return {}

    # Convert to pandas Timestamp if needed and truncate to hour
    ts = pd.Timestamp(pool_timestamp)
    hour_start = ts.floor("h")

    # Make timezone-naive if needed
    if hour_start.tz is not None:
        hour_start = hour_start.tz_localize(None)

    try:
        if hour_start in weather_df.index:
            return weather_df.loc[hour_start].to_dict()
    except (KeyError, TypeError):
        pass

    return {}


def merge_features(
    pool_df: pd.DataFrame,
    weather_df: pd.DataFrame,
    public_holidays: dict,
    school_vacations: list
) -> pd.DataFrame:
    """Join pool data with weather and holiday features.

    Args:
        pool_df: Pool occupancy DataFrame
        weather_df: Weather DataFrame indexed by hour
        public_holidays: Dictionary from load_public_holidays()
        school_vacations: List from load_school_holidays()

    Returns:
        DataFrame with all features merged
    """
    if pool_df.empty:
        return pd.DataFrame()

    # Add month column
    pool_df["month"] = pool_df["timestamp"].dt.month

    # Add holiday features
    pool_df["is_holiday"] = pool_df["timestamp"].apply(
        lambda ts: 1 if is_public_holiday(ts, public_holidays) else 0
    )
    pool_df["is_school_vacation"] = pool_df["timestamp"].apply(
        lambda ts: 1 if is_school_vacation(ts, school_vacations) else 0
    )

    # Add weather features
    weather_cols = ["temperature_c", "precipitation_mm", "weather_code", "cloud_cover_percent"]

    for col in weather_cols:
        pool_df[col] = None

    if not weather_df.empty:
        for idx, row in pool_df.iterrows():
            weather = align_weather(row["timestamp"], weather_df)
            for col in weather_cols:
                if col in weather:
                    pool_df.at[idx, col] = weather[col]

    return pool_df


def validate_data(df: pd.DataFrame) -> pd.DataFrame:
    """Validate and clean the output DataFrame.

    Args:
        df: DataFrame to validate

    Returns:
        Validated DataFrame

    Raises:
        ValueError: If validation fails
    """
    if df.empty:
        return df

    # Check occupancy_percent range
    invalid_occupancy = df[
        (df["occupancy_percent"] < 0) | (df["occupancy_percent"] > 100)
    ]
    if not invalid_occupancy.empty:
        logger.warning(f"Found {len(invalid_occupancy)} records with invalid occupancy_percent")
        df = df[
            (df["occupancy_percent"] >= 0) & (df["occupancy_percent"] <= 100)
        ]

    # Check for duplicates (include facility_type since same name can be pool and sauna)
    duplicates = df.duplicated(subset=["timestamp", "facility_name", "facility_type"], keep="first")
    if duplicates.any():
        logger.warning(f"Removing {duplicates.sum()} duplicate records")
        df = df[~duplicates]

    return df


def load_existing_data(output_path: Path) -> pd.DataFrame:
    """Load existing output file if it exists.

    Args:
        output_path: Path to the output CSV file

    Returns:
        Existing DataFrame or empty DataFrame
    """
    if output_path.exists():
        logger.info(f"Loading existing data from {output_path}")
        df = pd.read_csv(output_path, parse_dates=["timestamp"])
        # Make timezone-naive for internal processing (will add timezone back when saving)
        if df["timestamp"].dt.tz is not None:
            df["timestamp"] = df["timestamp"].dt.tz_localize(None)
        # Handle migration from old column name
        if "pool_name" in df.columns and "facility_name" not in df.columns:
            df = df.rename(columns={"pool_name": "facility_name"})
        return df
    return pd.DataFrame()


def transform(
    pool_dir: Path,
    weather_dir: Path,
    holiday_dir: Path,
    output_path: Path
) -> None:
    """Main transform pipeline.

    Args:
        pool_dir: Directory with pool JSON files
        weather_dir: Directory with weather JSON files
        holiday_dir: Directory with holiday JSON files
        output_path: Path for output CSV file
    """
    # Load facility aliases
    config_dir = Path(__file__).parent / "config"
    aliases = load_facility_aliases(config_dir)
    logger.info(f"Loaded {len(aliases)} facility aliases")

    # Load existing data to find the latest timestamp
    existing_df = load_existing_data(output_path)
    since = None
    if not existing_df.empty:
        since = existing_df["timestamp"].max()
        logger.info(f"Incremental mode: loading data since {since}")
    else:
        logger.info("No existing dataset found - processing all raw data files")

    # Load pool data
    logger.info(f"Loading pool data from {pool_dir}")
    pool_df = load_pool_data(pool_dir, since=since, aliases=aliases)
    if pool_df.empty:
        logger.warning("No new pool data to transform")
        return

    logger.info(f"Loaded {len(pool_df)} pool records")

    # Load weather data
    logger.info(f"Loading weather data from {weather_dir}")
    weather_df = load_weather_data(weather_dir)
    logger.info(f"Loaded {len(weather_df)} weather records")

    # Load holidays
    public_holidays_path = holiday_dir / "public_holidays.json"
    school_holidays_path = holiday_dir / "school_holidays.json"

    public_holidays = {}
    school_vacations = []

    if public_holidays_path.exists():
        public_holidays = load_public_holidays(public_holidays_path)
        logger.info(f"Loaded {len(public_holidays)} public holidays")
    else:
        logger.warning(f"Public holidays file not found: {public_holidays_path}")

    if school_holidays_path.exists():
        school_vacations = load_school_holidays(school_holidays_path)
        logger.info(f"Loaded {len(school_vacations)} school vacation periods")
    else:
        logger.warning(f"School holidays file not found: {school_holidays_path}")

    # Merge features
    logger.info("Merging features...")
    merged_df = merge_features(pool_df, weather_df, public_holidays, school_vacations)

    # Validate
    logger.info("Validating data...")
    validated_df = validate_data(merged_df)

    # Combine with existing data
    if not existing_df.empty:
        combined_df = pd.concat([existing_df, validated_df], ignore_index=True)
        # Remove any duplicates that might have crept in
        combined_df = combined_df.drop_duplicates(
            subset=["timestamp", "facility_name", "facility_type"],
            keep="last"
        )
    else:
        combined_df = validated_df

    # Sort and save
    combined_df = combined_df.sort_values(["timestamp", "facility_name"])

    # Ensure output directory exists
    output_path.parent.mkdir(parents=True, exist_ok=True)

    # Define column order
    columns = [
        "timestamp", "facility_name", "facility_type", "occupancy_percent",
        "is_open", "hour", "day_of_week", "month", "is_weekend",
        "is_holiday", "is_school_vacation",
        "temperature_c", "precipitation_mm", "weather_code", "cloud_cover_percent",
        "data_source"
    ]

    # Add data_source column
    combined_df["data_source"] = "historical"

    # Only include columns that exist
    columns = [c for c in columns if c in combined_df.columns]
    combined_df = combined_df[columns]

    # Add timezone to timestamps and format as ISO 8601
    combined_df["timestamp"] = pd.to_datetime(combined_df["timestamp"])
    if combined_df["timestamp"].dt.tz is None:
        combined_df["timestamp"] = combined_df["timestamp"].dt.tz_localize(TIMEZONE)
    combined_df["timestamp"] = combined_df["timestamp"].dt.strftime("%Y-%m-%dT%H:%M:%S%z")
    # Insert colon in timezone offset for ISO 8601 compliance (+0100 -> +01:00)
    combined_df["timestamp"] = combined_df["timestamp"].str.replace(
        r"(\+|-)(\d{2})(\d{2})$", r"\1\2:\3", regex=True
    )

    combined_df.to_csv(output_path, index=False)
    logger.info(f"Saved {len(combined_df)} records to {output_path}")

    # Generate facility_types.json mapping
    # Use composite key "type:name" to handle facilities with same name but different types
    # (e.g., "Cosimawellenbad" exists as both pool and sauna)
    facility_types_path = Path(__file__).parent / "config" / "facility_types.json"
    facility_types_path.parent.mkdir(parents=True, exist_ok=True)
    unique_facilities = combined_df[["facility_name", "facility_type"]].drop_duplicates()
    facility_types = {
        f"{row['facility_type']}:{row['facility_name']}": row["facility_type"]
        for _, row in unique_facilities.iterrows()
    }
    with open(facility_types_path, "w") as f:
        json.dump(facility_types, f, indent=2)
    logger.info(f"Saved facility types mapping to {facility_types_path}")


def main():
    parser = argparse.ArgumentParser(description="Transform pool data with weather and holiday features")
    parser.add_argument(
        "--pool-dir",
        type=str,
        default="pool_scrapes_raw",
        help="Directory with pool JSON files"
    )
    parser.add_argument(
        "--weather-dir",
        type=str,
        default="weather_raw",
        help="Directory with weather JSON files"
    )
    parser.add_argument(
        "--holiday-dir",
        type=str,
        default="holidays",
        help="Directory with holiday JSON files"
    )
    parser.add_argument(
        "--output",
        type=str,
        default="datasets/occupancy_historical.csv",
        help="Output CSV file path"
    )

    args = parser.parse_args()

    try:
        transform(
            pool_dir=Path(args.pool_dir),
            weather_dir=Path(args.weather_dir),
            holiday_dir=Path(args.holiday_dir),
            output_path=Path(args.output)
        )
    except Exception as e:
        logger.error(f"Transform failed: {e}")
        sys.exit(1)


if __name__ == "__main__":
    main()
