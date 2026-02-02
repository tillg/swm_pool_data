#!/usr/bin/env python3
"""Check raw scrape data for irregularities."""

import argparse
import json
import logging
import re
import subprocess
import sys
from datetime import datetime, timedelta
from pathlib import Path
from zoneinfo import ZoneInfo

TIMEZONE = ZoneInfo("Europe/Berlin")
GAP_THRESHOLD_HOURS = 2
HISTORICAL_DAYS = 30

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s - %(levelname)s - %(message)s"
)
logger = logging.getLogger(__name__)


def parse_capacity(raw_occupancy: str) -> int | None:
    """Parse capacity from raw_occupancy field.

    Args:
        raw_occupancy: String like "57/311 persons"

    Returns:
        Capacity as integer, or None if parsing fails
    """
    if not raw_occupancy:
        return None
    match = re.search(r"/(\d+)\s*persons?", raw_occupancy)
    if match:
        return int(match.group(1))
    return None


def extract_facilities_from_scrape(data: dict) -> list[dict]:
    """Extract all facilities from a scrape JSON.

    Args:
        data: Parsed JSON scrape data

    Returns:
        List of facility dicts with name, type, capacity
    """
    facilities = []
    for key, value in data.items():
        if not isinstance(value, list) or not value:
            continue
        if isinstance(value[0], dict) and "facility_type" in value[0]:
            for fac in value:
                capacity = parse_capacity(fac.get("raw_occupancy"))
                facilities.append({
                    "name": fac.get("pool_name"),
                    "type": fac.get("facility_type"),
                    "capacity": capacity,
                    "timestamp": fac.get("timestamp"),
                })
    return facilities


def load_scrapes_for_date(scrape_dir: Path, target_date: datetime) -> list[dict]:
    """Load all scrapes for a specific date.

    Args:
        scrape_dir: Directory containing pool_data_*.json files
        target_date: Date to load scrapes for

    Returns:
        List of parsed scrape dicts with timestamps
    """
    date_str = target_date.strftime("%Y%m%d")
    pattern = f"pool_data_{date_str}_*.json"
    scrapes = []

    for filepath in sorted(scrape_dir.glob(pattern)):
        try:
            with open(filepath, encoding="utf-8") as f:
                data = json.load(f)
            scrape_ts = data.get("scrape_timestamp")
            if scrape_ts:
                data["_filepath"] = filepath
                data["_parsed_timestamp"] = datetime.fromisoformat(scrape_ts)
                scrapes.append(data)
        except (json.JSONDecodeError, ValueError) as e:
            logger.warning(f"Skipping invalid file {filepath}: {e}")

    return scrapes


def get_historical_facilities(scrape_dir: Path, days: int = HISTORICAL_DAYS) -> set[tuple[str, str]]:
    """Get set of (type, name) tuples seen in historical scrapes.

    Args:
        scrape_dir: Directory containing pool_data_*.json files
        days: Number of days to look back

    Returns:
        Set of (facility_type, facility_name) tuples
    """
    facilities = set()
    today = datetime.now(TIMEZONE).date()

    for day_offset in range(1, days + 1):
        target_date = today - timedelta(days=day_offset)
        scrapes = load_scrapes_for_date(scrape_dir, datetime.combine(target_date, datetime.min.time()))
        for scrape in scrapes:
            for fac in extract_facilities_from_scrape(scrape):
                facilities.add((fac["type"], fac["name"]))

    return facilities


def get_historical_capacities(scrape_dir: Path, days: int = HISTORICAL_DAYS) -> dict[tuple[str, str], int]:
    """Get most recent capacity for each facility from historical scrapes.

    Args:
        scrape_dir: Directory containing pool_data_*.json files
        days: Number of days to look back

    Returns:
        Dict mapping (facility_type, facility_name) to capacity
    """
    capacities = {}
    today = datetime.now(TIMEZONE).date()

    for day_offset in range(1, days + 1):
        target_date = today - timedelta(days=day_offset)
        scrapes = load_scrapes_for_date(scrape_dir, datetime.combine(target_date, datetime.min.time()))
        for scrape in scrapes:
            for fac in extract_facilities_from_scrape(scrape):
                key = (fac["type"], fac["name"])
                if fac["capacity"] and key not in capacities:
                    capacities[key] = fac["capacity"]

    return capacities


def check_missing_facilities(
    today_scrapes: list[dict],
    historical_facilities: set[tuple[str, str]]
) -> list[str]:
    """Check for facilities missing for 2+ hours.

    Args:
        today_scrapes: List of today's scrape dicts
        historical_facilities: Set of (type, name) from history

    Returns:
        List of issue descriptions
    """
    if not today_scrapes:
        return []

    issues = []
    today_facilities = set()

    for scrape in today_scrapes:
        for fac in extract_facilities_from_scrape(scrape):
            today_facilities.add((fac["type"], fac["name"]))

    # Find facilities in history but not in today's scrapes
    missing = historical_facilities - today_facilities

    # Check if missing for 2+ hours by looking at scrape timestamps
    if missing and len(today_scrapes) >= 8:  # 8 scrapes = 2 hours at 15-min intervals
        first_scrape = min(s["_parsed_timestamp"] for s in today_scrapes)
        last_scrape = max(s["_parsed_timestamp"] for s in today_scrapes)
        duration = last_scrape - first_scrape

        if duration >= timedelta(hours=GAP_THRESHOLD_HOURS):
            for fac_type, fac_name in sorted(missing):
                issues.append(f"Missing facility: {fac_type}:{fac_name} (not seen in {len(today_scrapes)} scrapes over {duration})")

    return issues


def check_new_facilities(
    today_scrapes: list[dict],
    historical_facilities: set[tuple[str, str]]
) -> list[str]:
    """Check for new facilities not in historical data.

    Args:
        today_scrapes: List of today's scrape dicts
        historical_facilities: Set of (type, name) from history

    Returns:
        List of issue descriptions
    """
    issues = []
    today_facilities = set()

    for scrape in today_scrapes:
        for fac in extract_facilities_from_scrape(scrape):
            today_facilities.add((fac["type"], fac["name"]))

    new_facilities = today_facilities - historical_facilities

    for fac_type, fac_name in sorted(new_facilities):
        issues.append(f"New facility: {fac_type}:{fac_name}")

    return issues


def check_capacity_changes(
    today_scrapes: list[dict],
    historical_capacities: dict[tuple[str, str], int]
) -> list[str]:
    """Check for capacity changes compared to historical data.

    Args:
        today_scrapes: List of today's scrape dicts
        historical_capacities: Dict of (type, name) to capacity

    Returns:
        List of issue descriptions
    """
    issues = []
    today_capacities = {}

    for scrape in today_scrapes:
        for fac in extract_facilities_from_scrape(scrape):
            key = (fac["type"], fac["name"])
            if fac["capacity"] and key not in today_capacities:
                today_capacities[key] = fac["capacity"]

    for key, today_cap in today_capacities.items():
        if key in historical_capacities:
            hist_cap = historical_capacities[key]
            if today_cap != hist_cap:
                fac_type, fac_name = key
                issues.append(f"Capacity change: {fac_type}:{fac_name} ({hist_cap} -> {today_cap})")

    return issues


def check_scrape_gaps(scrape_dir: Path, target_date: datetime) -> list[str]:
    """Check for gaps of 2+ hours between scrapes.

    Args:
        scrape_dir: Directory containing pool_data_*.json files
        target_date: Date to check

    Returns:
        List of issue descriptions
    """
    scrapes = load_scrapes_for_date(scrape_dir, target_date)

    if len(scrapes) < 2:
        return [f"Insufficient scrapes: only {len(scrapes)} scrapes found for {target_date.date()}"]

    issues = []
    timestamps = sorted(s["_parsed_timestamp"] for s in scrapes)

    for i in range(1, len(timestamps)):
        gap = timestamps[i] - timestamps[i - 1]
        if gap >= timedelta(hours=GAP_THRESHOLD_HOURS):
            issues.append(
                f"Scrape gap: {gap} between "
                f"{timestamps[i-1].strftime('%H:%M')} and {timestamps[i].strftime('%H:%M')}"
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
    parser = argparse.ArgumentParser(description="Check raw scrape data for irregularities")
    parser.add_argument(
        "--scrape-dir",
        type=str,
        default="pool_scrapes_raw",
        help="Directory containing pool_data_*.json files"
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Don't create GitHub issues, just log what would be created"
    )
    args = parser.parse_args()

    scrape_dir = Path(args.scrape_dir)
    if not scrape_dir.exists():
        logger.error(f"Scrape directory not found: {scrape_dir}")
        sys.exit(1)

    today = datetime.now(TIMEZONE)
    logger.info(f"Checking raw scrapes for {today.date()}")

    # Load data
    logger.info("Loading historical data...")
    historical_facilities = get_historical_facilities(scrape_dir)
    historical_capacities = get_historical_capacities(scrape_dir)
    logger.info(f"Found {len(historical_facilities)} historical facilities")

    logger.info("Loading today's scrapes...")
    today_scrapes = load_scrapes_for_date(scrape_dir, today)
    logger.info(f"Found {len(today_scrapes)} scrapes for today")

    # Run checks
    all_issues = []

    issues = check_missing_facilities(today_scrapes, historical_facilities)
    all_issues.extend(issues)
    if issues:
        logger.warning(f"Found {len(issues)} missing facility issues")

    issues = check_new_facilities(today_scrapes, historical_facilities)
    all_issues.extend(issues)
    if issues:
        logger.warning(f"Found {len(issues)} new facility issues")

    issues = check_capacity_changes(today_scrapes, historical_capacities)
    all_issues.extend(issues)
    if issues:
        logger.warning(f"Found {len(issues)} capacity change issues")

    issues = check_scrape_gaps(scrape_dir, today)
    all_issues.extend(issues)
    if issues:
        logger.warning(f"Found {len(issues)} scrape gap issues")

    # Create GitHub issue if irregularities found
    if all_issues:
        title = f"Data Irregularities Detected - Raw Scrapes ({today.date()})"
        body = "## Raw Scrape Data Irregularities\n\n"
        body += f"Detected on: {today.isoformat()}\n\n"
        body += "### Issues Found\n\n"
        for issue in all_issues:
            body += f"- {issue}\n"
        body += "\n### Suggested Actions\n\n"
        body += "- For new facilities: Verify if intentional, update documentation\n"
        body += "- For missing facilities: Check if removed upstream or add to `facility_aliases.json`\n"
        body += "- For capacity changes: Verify if intentional change\n"
        body += "- For scrape gaps: Check scraper health and GitHub Actions logs\n"

        create_github_issue(title, body, dry_run=args.dry_run)
    else:
        logger.info("No irregularities found in raw scrape data")


if __name__ == "__main__":
    main()
