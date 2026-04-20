# Forecast File Format

**Status:** Implemented

## Overview

Historical and forecast data use a unified CSV format for easier downstream consumption.

| File | Description |
|------|-------------|
| `datasets/occupancy_historical.csv` | Historical observations from scraping |
| `datasets/occupancy_forecast.csv` | 48-hour predictions (regenerated daily) |

Both files share the same schema, distinguished by the `data_source` column.

## CSV Schema

| Column | Type | Notes |
| ------ | ---- | ----- |
| timestamp | ISO 8601 with timezone | `2025-01-28T14:00:00+01:00` |
| facility_name | string | e.g., "Cosimawellenbad" |
| facility_type | string | `pool`, `sauna`, or `ice_rink` |
| occupancy_percent | float | Predicted value for forecast |
| is_open | int/NULL | `1` or `0` for historical, `NULL` for forecast |
| hour | int | 0-23 |
| day_of_week | int | 0=Monday, 6=Sunday |
| month | int | 1-12 |
| is_weekend | int | 0 or 1 |
| is_holiday | int | 0 or 1 |
| is_school_vacation | int | 0 or 1 |
| temperature_c | float | Air temperature in °C |
| precipitation_mm | float | Precipitation in mm |
| weather_code | int | WMO weather code |
| cloud_cover_percent | float | 0-100% |
| data_source | string | `"historical"` or `"forecast"` |

**Format conventions:**
- NULL values: Literal string `NULL`
- Sort order: `(timestamp, facility_name)`
- Timestamps: ISO 8601 with timezone offset

## Key Files

| File | Purpose |
|------|---------|
| `src/transform.py` | Generates `occupancy_historical.csv` from raw JSON |
| `src/config/facility_types.json` | Facility name → type mapping (auto-generated) |
| `src/train/train.py` | Trains LightGBM model from historical data |
| `src/forecast/forecast.py` | Generates `occupancy_forecast.csv` using trained model |

## Workflows

| Workflow | Schedule | Output |
|----------|----------|--------|
| `transform.yml` | After scrape/weather | `occupancy_historical.csv` |
| `train.yml` | Weekly (Sunday 22:00 UTC) | `models/occupancy_model.pkl` |
| `forecast.yml` | Daily (05:00 UTC) | `occupancy_forecast.csv` |
