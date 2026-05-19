"""Tests for the AI opening-hours fallback helper."""

import json
from pathlib import Path

import pytest

from opening_hours_ai_fallback import (
    apply_file_updates,
    build_prompt,
    extract_response_payload,
    write_snapshot,
)


def _snapshot() -> dict:
    return {
        "scrape_timestamp": "2026-05-10T08:00:00+02:00",
        "scrape_metadata": {"total_facilities": 1, "method": "ai_fallback"},
        "facilities": [
            {
                "pool_name": "Dante-Winter-Warmfreibad",
                "facility_type": "pool",
                "status": "open",
                "url": "https://www.swm.de/baeder/freibaeder-muenchen/dantebad",
                "heading": "Öffnungszeiten Dantebad",
                "weekly_schedule": {
                    "monday": [{"open": "07:00", "close": "23:00"}],
                },
                "special_notes": [],
                "raw_section": "Öffnungszeiten Dantebad",
                "scraped_at": "2026-05-10T08:00:00+02:00",
            }
        ],
    }


def test_extract_response_payload_accepts_fenced_json():
    content = """```json
    {
      "snapshot": {"facilities": []},
      "file_updates": []
    }
    ```"""

    payload = extract_response_payload(content)

    assert payload == {"snapshot": {"facilities": []}, "file_updates": []}


def test_write_snapshot_uses_facility_opening_prefix(tmp_path):
    path = write_snapshot(_snapshot(), tmp_path)

    assert path.parent == tmp_path
    assert path.name.startswith("facility_opening_")
    assert path.suffix == ".json"
    assert json.loads(path.read_text(encoding="utf-8"))["facilities"][0]["pool_name"] == (
        "Dante-Winter-Warmfreibad"
    )


def test_apply_file_updates_rejects_paths_outside_scraper(tmp_path):
    scraper_dir = tmp_path / "scraper"
    scraper_dir.mkdir()

    with pytest.raises(ValueError, match="outside scraper directory"):
        apply_file_updates(
            [{"path": "../evil.py", "content": "print('no')"}],
            scraper_dir,
        )


def test_apply_file_updates_writes_relative_scraper_files(tmp_path):
    scraper_dir = tmp_path / "scraper"
    scraper_dir.mkdir()

    written = apply_file_updates(
        [{"path": "src/facility_pages.py", "content": "PAGE_BINDINGS = {}\n"}],
        scraper_dir,
    )

    assert written == [scraper_dir / "src" / "facility_pages.py"]
    assert (scraper_dir / "src" / "facility_pages.py").read_text(encoding="utf-8") == (
        "PAGE_BINDINGS = {}\n"
    )


def test_build_prompt_contains_required_agent_instructions(tmp_path):
    scraper_dir = tmp_path / "scraper"
    scraper_dir.mkdir()
    (scraper_dir / "scrape_opening_hours.py").write_text("print('scrape')\n")

    prompt = build_prompt(
        swm_base_url="https://www.swm.de",
        scraper_dir=scraper_dir,
        output_dir=tmp_path / "out",
        failure_log="heading not found",
        page_context={"https://www.swm.de/baeder/example": "Öffnungszeiten Example"},
    )

    assert "Playwright MCP" in prompt
    assert "scrape the current opening-hours data" in prompt
    assert "fix the deterministic scraper" in prompt
    assert "heading not found" in prompt
    assert "https://www.swm.de" in prompt
