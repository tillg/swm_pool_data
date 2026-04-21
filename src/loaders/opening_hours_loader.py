#!/usr/bin/env python3
"""Loader for the daily facility opening-hours snapshots.

Produces a deterministic overlay the forecast pipeline uses to mark
closed hours — see Specs/changes/integrate-opening-hours/architecture.md.
"""

from __future__ import annotations

import json
import logging
from datetime import datetime, time
from pathlib import Path
from typing import Any

logger = logging.getLogger(__name__)

WEEKDAY_NAMES = [
    "monday", "tuesday", "wednesday", "thursday",
    "friday", "saturday", "sunday",
]


def _resolve_alias(facility_name: str, facility_type: str, aliases: dict) -> str:
    """Type-aware alias resolution matching transform.resolve_facility_alias."""
    key = f"{facility_type}:{facility_name}"
    return aliases.get(key, facility_name)


def load_latest_snapshot(
    input_dir: Path,
    aliases: dict | None = None,
) -> dict[tuple[str, str], dict[str, Any]]:
    """Load the most recent `facility_opening_*.json` in *input_dir*.

    Returns a dict keyed by ``(facility_type, canonical_name)`` whose
    values are the raw facility entries (preserving ``status`` and, when
    present, ``weekly_schedule``).

    Returns an empty dict and logs a warning for any failure — missing
    directory, no matching files, unreadable/invalid JSON. The forecast
    caller treats an empty schedule as "unknown" and falls back to the
    model prediction, so this keeps the pipeline running.
    """
    aliases = aliases or {}
    input_dir = Path(input_dir)

    if not input_dir.is_dir():
        logger.warning(f"Opening-hours directory not found: {input_dir}")
        return {}

    snapshots = sorted(input_dir.glob("facility_opening_*.json"))
    if not snapshots:
        logger.warning(f"No facility_opening_*.json in {input_dir}")
        return {}

    latest = snapshots[-1]
    try:
        with open(latest, encoding="utf-8") as f:
            data = json.load(f)
    except (OSError, json.JSONDecodeError) as e:
        logger.warning(f"Failed to read {latest}: {e}")
        return {}

    facilities = data.get("facilities", [])
    schedules: dict[tuple[str, str], dict[str, Any]] = {}
    for entry in facilities:
        raw_name = entry.get("pool_name")
        facility_type = entry.get("facility_type")
        if not raw_name or not facility_type:
            continue
        canonical = _resolve_alias(raw_name, facility_type, aliases)
        schedules[(facility_type, canonical)] = entry

    logger.info(
        f"Loaded opening-hours snapshot {latest.name} "
        f"({len(schedules)} facilities)"
    )
    return schedules


def _parse_hhmm(value: str) -> time:
    hh, mm = value.split(":", 1)
    return time(int(hh), int(mm))


def is_facility_open(
    schedules: dict[tuple[str, str], dict[str, Any]],
    facility_type: str,
    facility_name: str,
    dt: datetime,
) -> bool | None:
    """Three-state opening-hours lookup.

    - Returns ``True``/``False`` when the facility appears in *schedules*.
    - Returns ``None`` when the facility is not present — the caller
      should log a warning and keep the model prediction.

    ``closed_for_season`` entries always return ``False`` regardless of
    weekday. Interval matching is half-open: ``open_time <= dt.time() <
    close_time``.
    """
    entry = schedules.get((facility_type, facility_name))
    if entry is None:
        return None

    if entry.get("status") == "closed_for_season":
        return False

    weekly = entry.get("weekly_schedule") or {}
    weekday = WEEKDAY_NAMES[dt.weekday()]
    intervals = weekly.get(weekday) or []

    current = dt.time()
    for interval in intervals:
        try:
            open_t = _parse_hhmm(interval["open"])
            close_t = _parse_hhmm(interval["close"])
        except (KeyError, ValueError):
            continue
        if open_t <= current < close_t:
            return True

    return False
