# Forecast ML

## Goal

Predict facility occupancy for the next 48 hours, pre-computed hourly for all facilities.

**Inputs:** timestamp, facility, weather forecast, holiday/school vacation flags

**Output:** predicted occupancy_percent (0-100)

---

## Model Approach

Single LightGBM gradient boosting model with facility as a categorical feature. Simpler than 13+ separate models, handles weather interactions well.

**Features:**

- `facility` (categorical)
- `hour`, `day_of_week`, `month`, `is_weekend`
- `is_holiday`, `is_school_vacation`
- `temperature_c`, `precipitation_mm`, `weather_code`

**Training:** Time-based split (last 10% for validation). Uses all available historical data from `occupancy_features.csv`.

**Metric:** Mean Absolute Error (MAE) in percentage points. Target: MAE < 15.

---

## Project Structure

```text
src/
  train/
    train.py
    hyperparameters.py
  forecast/
    forecast.py
models/
  occupancy_model.pkl
forecasts/
  forecast_latest.json
```

---

## Pipeline

### Training (weekly, Sunday night)

Loads `occupancy_features.csv`, trains model, logs MAE, saves to `models/occupancy_model.pkl`.

### Forecast (daily, 06:00)

Loads model, reads weather forecast from `weather_raw/`, generates 48h predictions for all facilities, saves to `forecasts/forecast_latest.json`.

**Output format:**

```json
{
  "generated_at": "2026-01-26T06:00:00+01:00",
  "forecasts": [
    {"facility": "Cosimawellenbad", "timestamp": "2026-01-26T10:00:00+01:00", "predicted_occupancy": 72.5}
  ]
}
```

---

## CLI Interface

Both scripts accept command-line args with sensible defaults matching our repo structure:

```bash
python src/train/train.py [--data PATH] [--output PATH]
python src/forecast/forecast.py [--model PATH] [--weather-dir PATH] [--output PATH]
```

---

## Error Handling

Fail with clear error messages. No silent failures. Specifically:

- Missing model file at forecast time → fail
- Incomplete weather forecast (< 48h) → fail

---

## GitHub Actions

**train.yml** - weekly Sunday night: train model, commit & push

**forecast.yml** - daily 06:00 Europe/Berlin: generate predictions, commit & push

---

## Dependencies

Add to `requirements.txt`:

- `lightgbm`
- `scikit-learn`
