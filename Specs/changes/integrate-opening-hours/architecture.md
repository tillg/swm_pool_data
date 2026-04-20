# Architecture: Integrate Opening Hours

Read [proposal.md](./proposal.md) and [domain.md](./domain.md) first.

## Technical approach

Treat opening hours as a **deterministic overlay** applied after the ML model
runs. The model's job is unchanged — predict `occupancy_percent` for every
hour, facility, and weather combination. The overlay then replaces predicted
values on hours the facility is scheduled closed. No retraining, no feature
engineering, no model changes.

This mirrors the pattern already used for holidays and school vacations: a
lightweight loader provides a lookup function, and a pure Python step in the
pipeline consumes it.

## Component overview

```mermaid
flowchart TB
    subgraph raw[Raw data]
        OHJson[(facility_openings_raw/<br/>facility_opening_*.json)]
    end

    subgraph loaders[src/loaders/]
        OHLoader[opening_hours_loader.py<br/><br/>load_latest_snapshot<br/>is_facility_open]
    end

    subgraph forecast[src/forecast/]
        ForecastPy[forecast.py]
        Overlay[apply_opening_hours_overlay]
    end

    subgraph config[src/config/]
        Aliases[facility_aliases.json]
    end

    subgraph output[Output]
        FCSV[(occupancy_forecast.csv)]
    end

    OHJson --> OHLoader
    Aliases --> OHLoader
    OHLoader --> Overlay
    ForecastPy --> Overlay
    Overlay --> FCSV

    style loaders fill:#e1f5ff
    style forecast fill:#fff3cd
```

## Data format: `facility_opening_*.json`

Produced by `scrape_opening_hours.py` in `tillg/swm_pool_scraper`.
Schema (actual output as of 2026-04):

```json
{
  "scrape_timestamp": "2026-04-20T04:00:00+02:00",
  "scrape_metadata": {
    "total_facilities": 17,
    "pools_count": 9,
    "saunas_count": 7,
    "ice_rinks_count": 1,
    "unique_pages_fetched": 10,
    "open_count": 16,
    "closed_for_season_count": 1,
    "method": "html"
  },
  "facilities": [
    {
      "pool_name": "Cosimawellenbad",
      "facility_type": "pool",
      "status": "open",
      "url": "https://www.swm.de/baeder/cosimawellenbad",
      "heading": "Öffnungszeiten Hallenbad",
      "weekly_schedule": {
        "monday":   [{"open": "07:30", "close": "23:00"}],
        "saturday": [{"open": "07:30", "close": "23:00"}]
      },
      "special_notes": ["Kassenschluss: 30 Minuten vor Ende der Öffnungszeit"],
      "raw_section": "...",
      "scraped_at": "2026-04-20T04:00:00+02:00"
    }
  ]
}
```

**Facility field is `pool_name`**, not `facility_name` — matching the
existing `pool_data_*.json` convention. The loader reads it as the
facility name and applies `facility_aliases.json` to resolve to the
canonical name.

**`status` values:**

- `"open"` → `weekly_schedule` populated with day→interval array.
- `"closed_for_season"` → `weekly_schedule` is empty; the overlay treats
  the facility as closed for every hour of the forecast horizon.

**Design choices (upstream):**

- **Weekly pattern only.** No date-specific overrides.
- **Weekday names as keys** match Python's `strftime("%A").lower()`.
- **Array of intervals per day** supports facilities with midday closures.
- **Times as `HH:MM` strings** in Berlin local time.
- **Fail loud on parse drift.** If the scraper can't produce either
  `"open"` with schedule or `"closed_for_season"`, it exits non-zero and
  writes nothing — the failed GitHub Actions run is the alert.

## Loader API

New file: `src/loaders/opening_hours_loader.py`

```python
def load_latest_snapshot(input_dir: Path, aliases: dict) -> dict:
    """Return {(facility_type, facility_name): schedule_entry} from the most
    recent facility_opening_*.json. schedule_entry is either:
      - {"status": "open", "weekly_schedule": {...}}
      - {"status": "closed_for_season"}
    Applies alias resolution on pool_name."""

def is_facility_open(
    schedules: dict,
    facility_type: str,
    facility_name: str,
    dt: datetime,
) -> bool | None:
    """True/False if schedule known. None if facility missing from snapshot.
    closed_for_season always returns False."""
```

Returning `None` (not `True`) for unknown facilities preserves today's
behavior: the forecast still emits a prediction and a warning, rather than
silently hiding a facility the model knows about. See
[proposal.md](./proposal.md#success-criteria) point 2.

## Overlay semantics

Pseudocode for the forecast step, replacing the end of
`generate_forecasts` in `src/forecast/forecast.py`:

```python
is_open_now = is_facility_open(
    schedules, facility_type, facility_name, ts_tz,
)

if is_open_now is False:
    prediction = 0.0
    is_open_value = 0
elif is_open_now is True:
    is_open_value = 1
else:  # None -> unknown facility
    is_open_value = "NULL"
    logger.warning(f"No opening hours known for {facility_type}:{facility_name}")
```

| `is_open_now` | `is_open` in CSV | `occupancy_percent` |
|---------------|------------------|---------------------|
| `True`        | `1`              | model prediction    |
| `False`       | `0`              | `0.0`               |
| `None`        | `NULL`           | model prediction    |

Historical CSV semantics are unchanged (`is_open` observed from the scraper).
Only the forecast CSV is touched.

## Workflow integration

```mermaid
sequenceDiagram
    participant Cron
    participant OHWorkflow as load_opening_hours.yml<br/>(daily 02:00 UTC)
    participant FCWorkflow as forecast.yml<br/>(existing - daily 05:00 UTC)
    participant Repo

    Cron->>OHWorkflow: 02:00 UTC daily
    OHWorkflow->>OHWorkflow: scraper/scrape_opening_hours.py
    OHWorkflow->>Repo: commit facility_opening_*.json
    Cron->>FCWorkflow: 05:00 UTC daily
    FCWorkflow->>Repo: read latest facility_opening_*.json
    FCWorkflow->>FCWorkflow: generate forecast with overlay
    FCWorkflow->>Repo: commit occupancy_forecast.csv
```

The new workflow runs **before** the existing daily forecast (~3h earlier)
so overlay data is fresh. If the opening-hours scraper fails, no snapshot
is written — the forecast still runs using whatever snapshot was committed
most recently, so the system degrades gracefully rather than blocking.

## Key decisions and tradeoffs

**Deterministic overlay vs. model feature**

- *Chosen:* deterministic overlay.
- *Rejected:* adding `is_scheduled_open` as a model feature.
- *Why:* the rule is known and perfect; the model would only dilute signal by
  re-learning it. Simpler pipelines are easier to debug.

**One consolidated JSON vs. one file per facility**

- *Chosen:* one JSON file per scrape run, all facilities inside.
- *Why:* matches `pool_data_*.json` convention. Fewer files to commit, easier
  to diff day-over-day to spot schedule changes.

**Weekly pattern vs. per-date schedule**

- *Chosen:* weekly pattern only.
- *Tradeoff:* public holidays and ad-hoc closures will not show as closed in
  the forecast. Holidays are already a model feature, so the model itself
  has some signal. Ad-hoc closures are rare and out of scope
  ([proposal.md](./proposal.md#scope)).

**`occupancy_percent = 0` vs. `NULL` for closed hours**

- *Chosen:* `0`.
- *Why:* the historical CSV has no `NULL` values in this column, and
  downstream consumers (plots, averages) handle `0` naturally. `is_open = 0`
  is the machine-readable signal that the value is a sentinel, not a
  prediction.

## Integration points and files affected

| File | Change |
|------|--------|
| `src/loaders/opening_hours_loader.py` | NEW |
| `facility_openings_raw/` | DONE — directory + README in place |
| `src/forecast/forecast.py` | Import loader; apply overlay in `generate_forecasts` |
| `.github/workflows/load_opening_hours.yml` | DONE — scrapes daily 02:00 UTC |
| `.github/workflows/forecast.yml` | No change needed (already runs at 05:00 UTC, 3h after the opening-hours scrape) |
| `README.md` | Document new data stream |
| `Specs/03_FORECAST_FILE_FORMAT.md` | Update `is_open` semantics for forecast rows |
| `CLAUDE.md` | Add opening-hours file location to project overview |

Deliberately **not touched**:

- `src/transform.py` — opening hours never enter the historical CSV.
- `src/train/train.py` — no new features.
- `models/occupancy_model.pkl` — model stays as-is.

## Risks

1. **Schedule scraping fragility.** If the swm.de HTML changes, the scraper
   stops producing snapshots. Mitigation: loader falls back to the most
   recent valid snapshot and logs a warning; the pipeline does not fail.
2. **Facility-name drift.** A renamed pool won't match the snapshot. The
   existing alias system (`04_ADAPT_TO_FACILITY_NAME_CHANGE.md`) is the fix
   — the loader must use it.
3. **Multi-interval days.** If SWM publishes morning+evening hours with a
   midday break, the array-of-intervals schema already supports it, but the
   loader's `is_facility_open` must check all intervals rather than just the
   first.
