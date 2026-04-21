# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Project Overview

This is a data collection and transformation pipeline for Munich SWM facility occupancy data. It scrapes real-time occupancy from SWM facilities (pools, saunas, ice rinks, etc.), combines it with weather and holiday data, and outputs ML-ready features.

## Common Commands

```bash
# Setup
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt

# Fetch weather data
python src/loaders/weather_loader.py --output-dir weather_raw

# Generate public holidays
python src/loaders/holiday_loader.py --output holidays/public_holidays.json --years 2025 2026 2027

# Run transform pipeline (must run from src directory)
cd src
python transform.py \
  --pool-dir ../pool_scrapes_raw \
  --weather-dir ../weather_raw \
  --holiday-dir ../holidays \
  --output ../datasets/occupancy_historical.csv

# Train model
cd src/train
python train.py

# Generate forecasts
cd src/forecast
python forecast.py
```

## Architecture

**Data Pipeline Flow:**
1. `scrape.yml` (every 15 min) → raw pool JSON to `pool_scrapes_raw/` → triggers transform
2. `load_opening_hours.yml` (daily 02:00 UTC) → `facility_openings_raw/facility_opening_*.json`
3. `load_weather.yml` (daily 05:00 UTC) → weather JSON to `weather_raw/` → triggers transform
4. `transform.yml` (triggered after scrape or weather) → `datasets/occupancy_historical.csv` + `src/config/facility_types.json`
5. `train.yml` (weekly) → `models/occupancy_model.pkl`
6. `forecast.yml` (daily 05:00 UTC) → `datasets/occupancy_forecast.csv` (applies opening-hours overlay at emit time)

**Key Components:**
- `src/loaders/weather_loader.py` - Fetches hourly weather from Open-Meteo API
- `src/loaders/holiday_loader.py` - Generates Bavarian public holidays
- `src/loaders/opening_hours_loader.py` - Loads latest opening-hours snapshot; used by `forecast.py` to overlay closed hours
- `src/transform.py` - Merges raw data into `occupancy_historical.csv`, generates `facility_types.json`
- `src/train/train.py` - Trains LightGBM model on historical data (filtered to `is_open == 1`)
- `src/forecast/forecast.py` - Generates 48-hour predictions using trained model + opening-hours overlay

**Key Files:**
- `datasets/occupancy_historical.csv` - Historical observations with weather/holiday features
- `datasets/occupancy_forecast.csv` - 48-hour predictions (same schema as historical)
- `facility_openings_raw/facility_opening_*.json` - Daily opening-hours snapshots (one per day)
- `src/config/facility_types.json` - Auto-generated facility name → type mapping
- `src/config/facility_aliases.json` - Legacy-to-canonical facility name aliases
- `models/occupancy_model.pkl` - Trained LightGBM model

**Data Sources:**
- Pool occupancy: [swm_pool_scraper](https://github.com/tillg/swm_pool_scraper) (external tool)
- Weather: Open-Meteo API (free, no auth required)
- Holidays: `holidays` Python package for public holidays; manual JSON for school vacations

**Important Notes:**
- Transform script must be run from `src/` directory due to relative imports
- All timestamps use Europe/Berlin timezone with ISO 8601 format
- Historical and forecast CSVs share the same schema (distinguished by `data_source` column)

## Git Commit Guidelines

**Caution:** Data files in this repo (e.g., `datasets/`, `pool_scrapes_raw/`, `weather_raw/`) are frequently written by external processes (GitHub Actions, scrapers). When committing:
- Always review `git status` and `git diff` carefully before staging
- Only commit files you intentionally changed
- Avoid `git add -A` or `git add .` which may accidentally include data files modified by background processes
- Stage specific files by name instead

<!-- gitnexus:start -->
# GitNexus — Code Intelligence

This project is indexed by GitNexus as **swm_pool_data** (1505 symbols, 1676 relationships, 10 execution flows). Use the GitNexus MCP tools to understand code, assess impact, and navigate safely.

> If any GitNexus tool warns the index is stale, run `npx gitnexus analyze` in terminal first.

## Always Do

- **MUST run impact analysis before editing any symbol.** Before modifying a function, class, or method, run `gitnexus_impact({target: "symbolName", direction: "upstream"})` and report the blast radius (direct callers, affected processes, risk level) to the user.
- **MUST run `gitnexus_detect_changes()` before committing** to verify your changes only affect expected symbols and execution flows.
- **MUST warn the user** if impact analysis returns HIGH or CRITICAL risk before proceeding with edits.
- When exploring unfamiliar code, use `gitnexus_query({query: "concept"})` to find execution flows instead of grepping. It returns process-grouped results ranked by relevance.
- When you need full context on a specific symbol — callers, callees, which execution flows it participates in — use `gitnexus_context({name: "symbolName"})`.

## When Debugging

1. `gitnexus_query({query: "<error or symptom>"})` — find execution flows related to the issue
2. `gitnexus_context({name: "<suspect function>"})` — see all callers, callees, and process participation
3. `READ gitnexus://repo/swm_pool_data/process/{processName}` — trace the full execution flow step by step
4. For regressions: `gitnexus_detect_changes({scope: "compare", base_ref: "main"})` — see what your branch changed

## When Refactoring

- **Renaming**: MUST use `gitnexus_rename({symbol_name: "old", new_name: "new", dry_run: true})` first. Review the preview — graph edits are safe, text_search edits need manual review. Then run with `dry_run: false`.
- **Extracting/Splitting**: MUST run `gitnexus_context({name: "target"})` to see all incoming/outgoing refs, then `gitnexus_impact({target: "target", direction: "upstream"})` to find all external callers before moving code.
- After any refactor: run `gitnexus_detect_changes({scope: "all"})` to verify only expected files changed.

## Never Do

- NEVER edit a function, class, or method without first running `gitnexus_impact` on it.
- NEVER ignore HIGH or CRITICAL risk warnings from impact analysis.
- NEVER rename symbols with find-and-replace — use `gitnexus_rename` which understands the call graph.
- NEVER commit changes without running `gitnexus_detect_changes()` to check affected scope.

## Tools Quick Reference

| Tool | When to use | Command |
|------|-------------|---------|
| `query` | Find code by concept | `gitnexus_query({query: "auth validation"})` |
| `context` | 360-degree view of one symbol | `gitnexus_context({name: "validateUser"})` |
| `impact` | Blast radius before editing | `gitnexus_impact({target: "X", direction: "upstream"})` |
| `detect_changes` | Pre-commit scope check | `gitnexus_detect_changes({scope: "staged"})` |
| `rename` | Safe multi-file rename | `gitnexus_rename({symbol_name: "old", new_name: "new", dry_run: true})` |
| `cypher` | Custom graph queries | `gitnexus_cypher({query: "MATCH ..."})` |

## Impact Risk Levels

| Depth | Meaning | Action |
|-------|---------|--------|
| d=1 | WILL BREAK — direct callers/importers | MUST update these |
| d=2 | LIKELY AFFECTED — indirect deps | Should test |
| d=3 | MAY NEED TESTING — transitive | Test if critical path |

## Resources

| Resource | Use for |
|----------|---------|
| `gitnexus://repo/swm_pool_data/context` | Codebase overview, check index freshness |
| `gitnexus://repo/swm_pool_data/clusters` | All functional areas |
| `gitnexus://repo/swm_pool_data/processes` | All execution flows |
| `gitnexus://repo/swm_pool_data/process/{name}` | Step-by-step execution trace |

## Self-Check Before Finishing

Before completing any code modification task, verify:
1. `gitnexus_impact` was run for all modified symbols
2. No HIGH/CRITICAL risk warnings were ignored
3. `gitnexus_detect_changes()` confirms changes match expected scope
4. All d=1 (WILL BREAK) dependents were updated

## CLI

- Re-index: `npx gitnexus analyze`
- Check freshness: `npx gitnexus status`
- Generate docs: `npx gitnexus wiki`

<!-- gitnexus:end -->
