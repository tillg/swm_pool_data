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
2. `load_weather.yml` (daily 05:00 UTC) → weather JSON to `weather_raw/` → triggers transform
3. `transform.yml` (triggered after scrape or weather) → `datasets/occupancy_historical.csv` + `src/config/facility_types.json`
4. `train.yml` (weekly) → `models/occupancy_model.pkl`
5. `forecast.yml` (daily) → `datasets/occupancy_forecast.csv`

**Key Components:**
- `src/loaders/weather_loader.py` - Fetches hourly weather from Open-Meteo API
- `src/loaders/holiday_loader.py` - Generates Bavarian public holidays
- `src/transform.py` - Merges raw data into `occupancy_historical.csv`, generates `facility_types.json`
- `src/train/train.py` - Trains LightGBM model on historical data
- `src/forecast/forecast.py` - Generates 48-hour predictions using trained model

**Key Files:**
- `datasets/occupancy_historical.csv` - Historical observations with weather/holiday features
- `datasets/occupancy_forecast.csv` - 48-hour predictions (same schema as historical)
- `src/config/facility_types.json` - Auto-generated facility name → type mapping
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
