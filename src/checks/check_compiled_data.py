#!/usr/bin/env python3
"""Check compiled data for irregularities."""

import argparse
import logging
import subprocess
import sys
from datetime import datetime, timedelta
from pathlib import Path
from zoneinfo import ZoneInfo

import pandas as pd

TIMEZONE = ZoneInfo("Europe/Berlin")
HISTORICAL_DAYS = 30
EXTENDED_ZERO_THRESHOLD_HOURS = 8
DAYTIME_START_HOUR = 6
DAYTIME_END_HOUR = 22

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s - %(levelname)s - %(message)s"
)
logger = logging.getLogger(__name__)


def load_historical_data(csv_path: Path) -> pd.DataFrame:
    """Load occupancy historical data.

    Args:
        csv_path: Path to occupancy_historical.csv

    Returns:
        DataFrame with parsed timestamps
    """
    df = pd.read_csv(csv_path, parse_dates=["timestamp"])
    return df


def get_historical_facility_types(df: pd.DataFrame, days: int = HISTORICAL_DAYS) -> set[str]:
    """Get set of facility types seen in historical data.

    Args:
        df: Historical data DataFrame
        days: Number of days to look back (from today, not from latest data)

    Returns:
        Set of facility type strings
    """
    cutoff = datetime.now(TIMEZONE) - timedelta(days=days)
    # Make cutoff naive for comparison with naive timestamps
    cutoff_naive = cutoff.replace(tzinfo=None)

    # Handle both timezone-aware and naive timestamps
    if df["timestamp"].dt.tz is not None:
        historical = df[df["timestamp"] >= cutoff]
    else:
        historical = df[df["timestamp"] >= cutoff_naive]

    return set(historical["facility_type"].unique())


def get_recent_facility_types(df: pd.DataFrame, hours: int = 24) -> set[str]:
    """Get set of facility types seen in recent data.

    Args:
        df: Historical data DataFrame
        hours: Number of hours to look back

    Returns:
        Set of facility type strings
    """
    cutoff = datetime.now(TIMEZONE) - timedelta(hours=hours)
    cutoff_naive = cutoff.replace(tzinfo=None)

    if df["timestamp"].dt.tz is not None:
        recent = df[df["timestamp"] >= cutoff]
    else:
        recent = df[df["timestamp"] >= cutoff_naive]

    return set(recent["facility_type"].unique())


def check_new_facility_types(
    df: pd.DataFrame,
    historical_types: set[str]
) -> list[str]:
    """Check for new facility types not in historical data.

    Args:
        df: Full DataFrame
        historical_types: Set of historical facility types

    Returns:
        List of issue descriptions
    """
    recent_types = get_recent_facility_types(df)
    new_types = recent_types - historical_types

    issues = []
    for fac_type in sorted(new_types):
        issues.append(f"New facility type: {fac_type}")

    return issues


def check_missing_facility_types(
    df: pd.DataFrame,
    historical_types: set[str]
) -> list[str]:
    """Check for facility types that existed historically but are now missing.

    Args:
        df: Full DataFrame
        historical_types: Set of historical facility types

    Returns:
        List of issue descriptions
    """
    recent_types = get_recent_facility_types(df)
    missing_types = historical_types - recent_types

    issues = []
    for fac_type in sorted(missing_types):
        issues.append(f"Missing facility type: {fac_type} (no data in last 24 hours)")

    return issues


def check_invalid_occupancy(df: pd.DataFrame) -> list[str]:
    """Check for occupancy values > 100%.

    Args:
        df: Historical data DataFrame

    Returns:
        List of issue descriptions
    """
    # Only check recent data (last 24 hours)
    cutoff = datetime.now(TIMEZONE) - timedelta(hours=24)
    cutoff_naive = cutoff.replace(tzinfo=None)

    if df["timestamp"].dt.tz is not None:
        recent = df[df["timestamp"] >= cutoff]
    else:
        recent = df[df["timestamp"] >= cutoff_naive]

    invalid = recent[recent["occupancy_percent"] > 100]

    issues = []
    if not invalid.empty:
        for _, row in invalid.head(10).iterrows():  # Limit to first 10
            issues.append(
                f"Invalid occupancy: {row['facility_type']}:{row['facility_name']} "
                f"at {row['occupancy_percent']}% ({row['timestamp']})"
            )
        if len(invalid) > 10:
            issues.append(f"... and {len(invalid) - 10} more invalid occupancy records")

    return issues


def check_extended_zero_occupancy(
    df: pd.DataFrame,
    threshold_hours: int = EXTENDED_ZERO_THRESHOLD_HOURS
) -> list[str]:
    """Check for facilities at 0% for extended periods during daytime.

    Only flags 0% occupancy during daytime hours (6:00-22:00) for threshold+ hours.

    Args:
        df: Historical data DataFrame
        threshold_hours: Minimum hours of continuous 0% to flag

    Returns:
        List of issue descriptions
    """
    # Only check recent data (last 48 hours to capture extended periods)
    cutoff = datetime.now(TIMEZONE) - timedelta(hours=48)
    cutoff_naive = cutoff.replace(tzinfo=None)

    if df["timestamp"].dt.tz is not None:
        recent = df[df["timestamp"] >= cutoff].copy()
    else:
        recent = df[df["timestamp"] >= cutoff_naive].copy()

    if recent.empty:
        return []

    # Filter to daytime hours only
    recent = recent[
        (recent["hour"] >= DAYTIME_START_HOUR) &
        (recent["hour"] < DAYTIME_END_HOUR)
    ]

    issues = []

    # Group by facility and check for extended zeros
    for (fac_type, fac_name), group in recent.groupby(["facility_type", "facility_name"]):
        zero_records = group[group["occupancy_percent"] == 0]
        if len(zero_records) == 0:
            continue

        # Check if zeros span threshold hours
        zero_records = zero_records.sort_values("timestamp")
        timestamps = zero_records["timestamp"].tolist()

        if len(timestamps) < 2:
            continue

        # Simple check: if first and last zero are threshold+ hours apart
        first_zero = timestamps[0]
        last_zero = timestamps[-1]

        # Handle timezone-aware vs naive
        if hasattr(first_zero, "tzinfo") and first_zero.tzinfo is not None:
            duration = last_zero - first_zero
        else:
            duration = pd.Timestamp(last_zero) - pd.Timestamp(first_zero)

        if duration >= timedelta(hours=threshold_hours):
            issues.append(
                f"Extended zero occupancy: {fac_type}:{fac_name} "
                f"at 0% for {duration} during daytime hours"
            )

    return issues


def create_github_issue(title: str, body: str, dry_run: bool = False) -> bool:
    """Create a GitHub issue using gh CLI.

    Args:
        title: Issue title
        body: Issue body
        dry_run: If True, only log what would be created

    Returns:
        True if issue created successfully
    """
    if dry_run:
        logger.info(f"[DRY RUN] Would create issue: {title}")
        logger.info(f"[DRY RUN] Body:\n{body}")
        return True

    try:
        result = subprocess.run(
            ["gh", "issue", "create", "--title", title, "--body", body, "--label", "data-irregularity"],
            capture_output=True,
            text=True,
            check=True,
        )
        logger.info(f"Created issue: {result.stdout.strip()}")
        return True
    except subprocess.CalledProcessError as e:
        logger.error(f"Failed to create issue: {e.stderr}")
        return False
    except FileNotFoundError:
        logger.error("gh CLI not found. Install GitHub CLI to create issues.")
        return False


def main():
    parser = argparse.ArgumentParser(description="Check compiled data for irregularities")
    parser.add_argument(
        "--csv",
        type=str,
        default="datasets/occupancy_historical.csv",
        help="Path to occupancy_historical.csv"
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Don't create GitHub issues, just log what would be created"
    )
    args = parser.parse_args()

    csv_path = Path(args.csv)
    if not csv_path.exists():
        logger.error(f"CSV file not found: {csv_path}")
        sys.exit(1)

    today = datetime.now(TIMEZONE)
    logger.info(f"Checking compiled data as of {today.date()}")

    # Load data
    logger.info("Loading historical data...")
    df = load_historical_data(csv_path)
    logger.info(f"Loaded {len(df)} records")

    historical_types = get_historical_facility_types(df)
    logger.info(f"Found {len(historical_types)} historical facility types: {historical_types}")

    # Run checks
    all_issues = []

    issues = check_new_facility_types(df, historical_types)
    all_issues.extend(issues)
    if issues:
        logger.warning(f"Found {len(issues)} new facility type issues")

    issues = check_missing_facility_types(df, historical_types)
    all_issues.extend(issues)
    if issues:
        logger.warning(f"Found {len(issues)} missing facility type issues")

    issues = check_invalid_occupancy(df)
    all_issues.extend(issues)
    if issues:
        logger.warning(f"Found {len(issues)} invalid occupancy issues")

    issues = check_extended_zero_occupancy(df)
    all_issues.extend(issues)
    if issues:
        logger.warning(f"Found {len(issues)} extended zero occupancy issues")

    # Create GitHub issue if irregularities found
    if all_issues:
        title = f"Data Irregularities Detected - Compiled Data ({today.date()})"
        body = "## Compiled Data Irregularities\n\n"
        body += f"Detected on: {today.isoformat()}\n\n"
        body += "### Issues Found\n\n"
        for issue in all_issues:
            body += f"- {issue}\n"
        body += "\n### Suggested Actions\n\n"
        body += "- For new facility types: Verify if intentional upstream change\n"
        body += "- For missing facility types: Check if removed or renamed upstream\n"
        body += "- For invalid occupancy: Check raw data source for errors\n"
        body += "- For extended zero occupancy: Verify facility is still operational\n"

        create_github_issue(title, body, dry_run=args.dry_run)
    else:
        logger.info("No irregularities found in compiled data")


if __name__ == "__main__":
    main()
