#!/usr/bin/env python3
"""AI fallback for the daily SWM opening-hours scraper.

The deterministic scraper remains the source of truth. This helper is only
called after that scraper fails. It asks an OpenAI-compatible model for two
artifacts:

1. A complete opening-hours snapshot for the current run.
2. Full-file updates for the checked-out deterministic scraper, so the next
   scheduled run can succeed without the fallback.
"""

from __future__ import annotations

import argparse
import json
import os
import re
import sys
from datetime import datetime
from pathlib import Path
from typing import Any

import requests
from bs4 import BeautifulSoup


SCRAPER_CONTEXT_FILES = (
    "scrape_opening_hours.py",
    "src/facility_pages.py",
    "src/facilities.py",
    "src/opening_hours_parser.py",
    "src/opening_hours_scraper.py",
    "src/opening_hours_model.py",
)


def _read_text(path: Path, max_chars: int = 24_000) -> str:
    try:
        text = path.read_text(encoding="utf-8")
    except OSError:
        return ""
    if len(text) > max_chars:
        return text[:max_chars] + "\n... [truncated]"
    return text


def _chat_completions_url(base_url: str) -> str:
    base_url = base_url.rstrip("/")
    if base_url.endswith("/chat/completions"):
        return base_url
    return f"{base_url}/chat/completions"


def extract_response_payload(content: str) -> dict[str, Any]:
    """Parse the model's strict JSON response, allowing a fenced block."""
    stripped = content.strip()
    fenced = re.match(r"^```(?:json)?\s*(.*?)\s*```$", stripped, re.DOTALL)
    if fenced:
        stripped = fenced.group(1).strip()
    payload = json.loads(stripped)
    if not isinstance(payload, dict):
        raise ValueError("AI response must be a JSON object")
    return payload


def validate_snapshot(snapshot: dict[str, Any]) -> None:
    facilities = snapshot.get("facilities")
    if not isinstance(facilities, list) or not facilities:
        raise ValueError("snapshot.facilities must be a non-empty list")
    for index, entry in enumerate(facilities):
        if not isinstance(entry, dict):
            raise ValueError(f"snapshot.facilities[{index}] must be an object")
        for field in ("pool_name", "facility_type", "status", "url", "scraped_at"):
            if not entry.get(field):
                raise ValueError(f"snapshot.facilities[{index}] missing {field}")
        status = entry.get("status")
        if status == "open" and not entry.get("weekly_schedule"):
            raise ValueError(f"open facility missing weekly_schedule: {entry['pool_name']}")


def write_snapshot(snapshot: dict[str, Any], output_dir: Path) -> Path:
    validate_snapshot(snapshot)
    output_dir.mkdir(parents=True, exist_ok=True)
    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    path = output_dir / f"facility_opening_{timestamp}.json"
    path.write_text(
        json.dumps(snapshot, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    return path


def apply_file_updates(updates: list[dict[str, str]], scraper_dir: Path) -> list[Path]:
    if not updates:
        raise ValueError("AI response must include at least one scraper file update")

    scraper_root = scraper_dir.resolve()
    written: list[Path] = []
    for update in updates:
        rel_path = update.get("path")
        content = update.get("content")
        if not rel_path or content is None:
            raise ValueError("Each file update requires path and content")
        target = (scraper_root / rel_path).resolve()
        try:
            target.relative_to(scraper_root)
        except ValueError as exc:
            raise ValueError(f"Refusing to write outside scraper directory: {rel_path}") from exc
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(content, encoding="utf-8")
        written.append(target)
    return written


def _scraper_file_context(scraper_dir: Path) -> str:
    parts = []
    for rel_path in SCRAPER_CONTEXT_FILES:
        text = _read_text(scraper_dir / rel_path)
        if text:
            parts.append(f"### {rel_path}\n```python\n{text}\n```")
    return "\n\n".join(parts)


def extract_page_text(html: str, max_chars: int = 60_000) -> str:
    """Plain-text view of an SWM page, the same way the deterministic parser sees it.

    The schedule on swm.de lives in a content block under an h2/h3 heading; the
    block is rendered server-side as line-separated text ("Mo bis Fr:\\n7 bis 23
    Uhr"). Whitespace-collapsing the raw HTML destroys those line breaks and
    hides the schedule from the model.
    """
    soup = BeautifulSoup(html, "html.parser")
    for tag in soup(["script", "style", "noscript"]):
        tag.decompose()
    text = soup.get_text(separator="\n", strip=True)
    text = re.sub(r"\n{3,}", "\n\n", text)
    if len(text) > max_chars:
        return text[:max_chars] + "\n... [truncated]"
    return text


def collect_page_context(swm_base_url: str, scraper_dir: Path) -> dict[str, str]:
    """Fetch current SWM page text for URLs referenced by facility_pages.py."""
    facility_pages = _read_text(scraper_dir / "src" / "facility_pages.py", max_chars=80_000)
    urls = sorted(set(re.findall(r"https://www\.swm\.de/baeder/[^\"']+", facility_pages)))
    if swm_base_url.rstrip("/") != "https://www.swm.de":
        urls = [url.replace("https://www.swm.de", swm_base_url.rstrip("/"), 1) for url in urls]

    context: dict[str, str] = {}
    session = requests.Session()
    session.headers.update({"User-Agent": "swm-pool-data-ai-fallback/1.0"})
    for url in urls:
        try:
            response = session.get(url, timeout=30)
            response.raise_for_status()
        except requests.RequestException as exc:
            context[url] = f"FETCH ERROR: {exc}"
            continue
        context[url] = extract_page_text(response.text)
    return context


def build_prompt(
    *,
    swm_base_url: str,
    scraper_dir: Path,
    output_dir: Path,
    failure_log: str,
    page_context: dict[str, str],
) -> str:
    page_parts = [f"### {url}\n{text}" for url, text in page_context.items()]
    return f"""You are the emergency AI fallback for the SWM pool opening-hours pipeline.

Use Playwright MCP to analyse the current SWM pages starting from {swm_base_url}.
The deterministic scraper failed, so your job is to:

1. scrape the current opening-hours data for every configured facility and produce one complete snapshot JSON;
2. fix the deterministic scraper under {scraper_dir} so the same deterministic command runs without error next time.

If Playwright MCP is unavailable in your runtime, use the supplied current page HTML/text context below, but still produce the same artifacts. Do not invent facilities. Preserve the existing snapshot shape used by facility_openings_raw files. For temporarily closed facilities, use status "closed_for_season", an empty weekly_schedule object, and include the closure reason in special_notes/raw_section.

Hard rules — these are validated and the run will fail if you break them:
- Every facility with status "open" MUST have a non-empty weekly_schedule populated from the supplied page text. Empty schedules with placeholder notes (e.g. "Manual fallback required") are rejected.
- If you genuinely cannot read a schedule from the page text, OMIT that facility from the snapshot rather than emitting a placeholder. A partial snapshot is preferred over fake data.
- file_updates must FIX the deterministic parser to handle the new page layout, not silence its errors. Do NOT add code paths that return empty schedules, swallow exceptions, or downgrade ParseError into success. The parser MUST keep raising on unrecognised pages — that error is what triggers this fallback.

Return exactly one JSON object and no prose. The JSON schema is:
{{
  "snapshot": {{
    "scrape_timestamp": "ISO-8601 timestamp",
    "scrape_metadata": {{"method": "ai_fallback", "total_facilities": 17}},
    "facilities": [{{
      "pool_name": "canonical facility name",
      "facility_type": "pool|sauna|ice_rink",
      "status": "open|closed_for_season",
      "url": "source URL",
      "heading": "matched heading or null",
      "weekly_schedule": {{"monday": [{{"open": "HH:MM", "close": "HH:MM"}}]}},
      "special_notes": ["notes"],
      "raw_section": "source text used for this facility",
      "scraped_at": "ISO-8601 timestamp"
    }}]
  }},
  "file_updates": [{{
    "path": "relative/path/inside/scraper.py",
    "content": "complete replacement file contents"
  }}]
}}

The output snapshot will be written to {output_dir}. File updates must be minimal and limited to the checked-out scraper repository.

Failure log:
```text
{failure_log[-20_000:]}
```

Deterministic scraper source:
{_scraper_file_context(scraper_dir)}

Current page context:
{chr(10).join(page_parts)}
"""


def call_openai_chat(
    *,
    base_url: str,
    api_key: str,
    model: str,
    prompt: str,
    timeout: int,
) -> str:
    response = requests.post(
        _chat_completions_url(base_url),
        headers={
            "Authorization": f"Bearer {api_key}",
            "Content-Type": "application/json",
        },
        json={
            "model": model,
            "messages": [
                {
                    "role": "system",
                    "content": "Return strict JSON only. You repair data pipelines safely.",
                },
                {"role": "user", "content": prompt},
            ],
            "temperature": 0,
        },
        timeout=timeout,
    )
    response.raise_for_status()
    body = response.json()
    return body["choices"][0]["message"]["content"]


def _env(*names: str) -> str | None:
    for name in names:
        value = os.environ.get(name)
        if value:
            return value
    return None


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="AI fallback for SWM opening hours")
    parser.add_argument("--scraper-dir", type=Path, default=Path("scraper"))
    parser.add_argument("--output-dir", type=Path, default=Path("facility_openings_raw"))
    parser.add_argument("--failure-log", type=Path, default=Path("opening_hours_deterministic.log"))
    parser.add_argument("--response-log", type=Path, default=Path("opening_hours_ai_response.txt"))
    parser.add_argument("--swm-base-url", default=_env("SWM_BASE_URL") or "https://www.swm.de")
    parser.add_argument("--openai-base-url", default=_env("AI_OPENAI_BASE_URL", "OPENAI_BASE_URL"))
    parser.add_argument("--openai-api-key", default=_env("AI_OPENAI_API_KEY", "OPENAI_API_KEY"))
    parser.add_argument("--openai-model", default=_env("AI_OPENAI_MODEL", "OPENAI_MODEL") or "gpt-4.1")
    parser.add_argument("--timeout", type=int, default=240)
    args = parser.parse_args(argv)

    if not args.openai_base_url:
        print("Missing --openai-base-url or AI_OPENAI_BASE_URL", file=sys.stderr)
        return 2
    if not args.openai_api_key:
        print("Missing --openai-api-key or AI_OPENAI_API_KEY", file=sys.stderr)
        return 2
    if not args.scraper_dir.is_dir():
        print(f"Scraper directory not found: {args.scraper_dir}", file=sys.stderr)
        return 2

    failure_log = _read_text(args.failure_log, max_chars=60_000)
    page_context = collect_page_context(args.swm_base_url, args.scraper_dir)
    prompt = build_prompt(
        swm_base_url=args.swm_base_url,
        scraper_dir=args.scraper_dir,
        output_dir=args.output_dir,
        failure_log=failure_log,
        page_context=page_context,
    )

    content = call_openai_chat(
        base_url=args.openai_base_url,
        api_key=args.openai_api_key,
        model=args.openai_model,
        prompt=prompt,
        timeout=args.timeout,
    )
    # Persist raw response before parsing so failed runs can still be debugged.
    args.response_log.parent.mkdir(parents=True, exist_ok=True)
    args.response_log.write_text(content, encoding="utf-8")
    print(f"Saved raw AI response: {args.response_log}")
    payload = extract_response_payload(content)
    snapshot = payload.get("snapshot")
    file_updates = payload.get("file_updates")
    if not isinstance(snapshot, dict):
        raise ValueError("AI response missing snapshot object")
    if not isinstance(file_updates, list):
        raise ValueError("AI response missing file_updates list")

    snapshot_path = write_snapshot(snapshot, args.output_dir)
    written = apply_file_updates(file_updates, args.scraper_dir)
    print(f"Wrote fallback snapshot: {snapshot_path}")
    for path in written:
        print(f"Updated scraper file: {path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
