#!/usr/bin/env python3
"""Holiday data loader for Bavaria, Germany."""

import argparse
import json
import logging
from datetime import date, datetime
from pathlib import Path
from zoneinfo import ZoneInfo

import holidays as holidays_lib

TIMEZONE = ZoneInfo("Europe/Berlin")

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s - %(levelname)s - %(message)s"
)
logger = logging.getLogger(__name__)


def generate_public_holidays(years: list[int]) -> dict:
    """Generate Bavarian public holidays using holidays package.

    Args:
        years: List of years to generate holidays for

    Returns:
        Dictionary with holiday data in our schema
    """
    bavaria_holidays = holidays_lib.Germany(prov="BY", years=years)

    holiday_list = []
    for dt, name in sorted(bavaria_holidays.items()):
        holiday_list.append({
            "date": dt.isoformat(),
            "name": name
        })

    return {
        "generated_at": datetime.now(TIMEZONE).isoformat(),
        "region": "DE-BY",
        "years": sorted(years),
        "holidays": holiday_list
    }


def load_public_holidays(path: Path) -> dict[date, str]:
    """Load public holidays from JSON file.

    Args:
        path: Path to public_holidays.json

    Returns:
        Dictionary mapping date to holiday name
    """
    with open(path, encoding="utf-8") as f:
        data = json.load(f)

    return {
        date.fromisoformat(h["date"]): h["name"]
        for h in data.get("holidays", [])
    }


def load_school_holidays(path: Path) -> list[tuple[date, date]]:
    """Load school vacation date ranges.

    Args:
        path: Path to school_holidays.json

    Returns:
        List of (start_date, end_date) tuples
    """
    with open(path, encoding="utf-8") as f:
        data = json.load(f)

    vacations = []
    for v in data.get("vacations", []):
        start = date.fromisoformat(v["start"])
        end = date.fromisoformat(v["end"])
        vacations.append((start, end))

    return vacations


def is_public_holiday(dt: datetime | date, holidays_dict: dict[date, str]) -> bool:
    """Check if datetime falls on a public holiday.

    Args:
        dt: Datetime or date to check
        holidays_dict: Dictionary from load_public_holidays()

    Returns:
        True if date is a public holiday
    """
    check_date = dt.date() if isinstance(dt, datetime) else dt
    return check_date in holidays_dict


def is_school_vacation(dt: datetime | date, vacations: list[tuple[date, date]]) -> bool:
    """Check if datetime falls within school vacation.

    Args:
        dt: Datetime or date to check
        vacations: List from load_school_holidays()

    Returns:
        True if date is within a school vacation period
    """
    check_date = dt.date() if isinstance(dt, datetime) else dt
    return any(start <= check_date <= end for start, end in vacations)


def save_public_holidays(data: dict, output_path: Path) -> Path:
    """Save public holidays to JSON file.

    Args:
        data: Holiday data dictionary
        output_path: Path to save the file

    Returns:
        Path to the saved file
    """
    output_path = Path(output_path)
    output_path.parent.mkdir(parents=True, exist_ok=True)

    with open(output_path, "w", encoding="utf-8") as f:
        json.dump(data, f, indent=2, ensure_ascii=False)

    logger.info(f"Saved public holidays to {output_path}")
    return output_path


def main():
    parser = argparse.ArgumentParser(description="Generate public holidays for Bavaria")
    parser.add_argument(
        "--output",
        type=str,
        default="holidays/public_holidays.json",
        help="Output file path"
    )
    parser.add_argument(
        "--years",
        type=int,
        nargs="+",
        default=[2025, 2026, 2027],
        help="Years to generate holidays for"
    )

    args = parser.parse_args()

    logger.info(f"Generating public holidays for years: {args.years}")
    data = generate_public_holidays(args.years)
    logger.info(f"Generated {len(data['holidays'])} holidays")

    save_public_holidays(data, Path(args.output))


if __name__ == "__main__":
    main()
