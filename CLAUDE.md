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
  --output ../datasets/occupancy_features.csv
```

## Architecture

**Data Pipeline Flow:**
1. `scrape.yml` (every 15 min) → raw pool JSON to `pool_scrapes_raw/` → triggers transform
2. `load_weather.yml` (daily 05:00 UTC) → weather JSON to `weather_raw/` → triggers transform
3. `transform.yml` (triggered after scrape or weather update) → merged CSV to `datasets/occupancy_features.csv`

**Key Components:**
- `src/loaders/weather_loader.py` - Fetches hourly weather from Open-Meteo API for Munich
- `src/loaders/holiday_loader.py` - Generates Bavarian public holidays; school holidays are manually maintained in `holidays/school_holidays.json`
- `src/transform.py` - Main pipeline that:
  - Loads facility JSON files (auto-discovers all facility types: pools, saunas, ice rinks, etc.)
  - Supports incremental loading via `since` parameter
  - Aligns weather data by hour
  - Adds holiday/school vacation flags
  - Deduplicates and appends to existing CSV

**Data Sources:**
- Pool occupancy: [swm_pool_scraper](https://github.com/tillg/swm_pool_scraper) (external tool)
- Weather: Open-Meteo API (free, no auth required)
- Holidays: `holidays` Python package for public holidays; manual JSON for school vacations

**Important Notes:**
- Transform script must be run from `src/` directory due to relative imports
- All timestamps use Europe/Berlin timezone
- Weather data uses WMO weather codes
- Facility data includes all SWM facility types (pools, saunas, ice rinks, etc.) - automatically discovered from raw JSON
