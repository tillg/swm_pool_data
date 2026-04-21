# Implementation Plan: Integrate Opening Hours

Read [proposal.md](./proposal.md) and [architecture.md](./architecture.md)
first.

Tasks are ordered: earlier ones unblock later ones.

## 1. Scaffolding

- [x] Directory `facility_openings_raw/` exists with a `README.md` so the
      scraper has a commit target.
- [x] Workflow `.github/workflows/load_opening_hours.yml` invokes
      `scrape_opening_hours.py` daily at 02:00 UTC.
- [x] Fixture snapshot at
      `src/tests/fixtures/facility_opening_20260420_040000.json` covers
      two pool entries (one with multi-interval Tuesday), one aliased
      sauna, and one `closed_for_season` ice rink.

## 2. Opening-hours loader

- [x] `src/loaders/opening_hours_loader.py` with:
  - [x] `load_latest_snapshot(input_dir, aliases)` returning
        `{(facility_type, canonical_name): schedule_entry}`.
  - [x] `is_facility_open(schedules, facility_type, facility_name, dt)`
        three-state (True/False/None), iterating all intervals per day,
        returning False for `closed_for_season`.
  - [x] Graceful handling for missing dir/file/malformed JSON.
- [x] `src/tests/test_opening_hours_loader.py` — all 14 tests pass:
  - [x] Hour inside interval / just before close / at close / before open.
  - [x] Multi-interval midday gap → False; second interval → True.
  - [x] `closed_for_season` every weekday → False.
  - [x] Facility missing → None.
  - [x] Alias resolved, canonical-name query works, legacy-name query
        returns None.

## 3. Forecast overlay

- [x] `src/forecast/forecast.py`:
  - [x] `--opening-hours-dir` CLI flag (default
        `../../facility_openings_raw`).
  - [x] Loads aliases via a local `_load_facility_aliases` helper.
  - [x] Calls `load_latest_snapshot` once at startup; logs snapshot
        filename and facility count.
  - [x] `generate_forecasts` applies precedence table: `False` → `(0, 0.0)`;
        `True` → `(1, prediction)`; `None` → `(NULL, prediction)` with a
        single warning per unknown facility.
- [x] `src/tests/test_forecast_overlay.py` — 6 tests covering all three
      precedence branches, multi-hour warn-once behavior, `closed_for_season`,
      and empty-snapshot fallback.

## 4. Workflow

- [x] `.github/workflows/load_opening_hours.yml` exists:
  - [x] Cron: daily at `02:00 UTC` (3h before the existing forecast run).
  - [x] Manual trigger: `workflow_dispatch`.
  - [x] Checks out `tillg/swm_pool_scraper` and runs
        `scrape_opening_hours.py --output-dir facility_openings_raw`.
  - [x] Commits only `facility_openings_raw/` with the three-retry push
        loop matching `scrape.yml`.
- [x] `.github/workflows/forecast.yml` still runs at 05:00 UTC; the 3h
      margin is enough to pick up the fresh snapshot without a
      `workflow_run` dependency.

## 5. Documentation

- [x] `README.md` updated: new directory in repo-structure tree, new
      "Opening Hours" subsection under Data Formats, pipeline ASCII
      diagram updated, automation-schedule table includes
      `load_opening_hours.yml`. Pick-up note removed.
- [x] `Specs/changes/forecast-file-format/proposal.md` updated: `is_open`
      row now describes the deterministic overlay with `1` / `0` / `NULL`.
- [x] `CLAUDE.md` updated: pipeline flow includes opening hours step,
      key components lists `opening_hours_loader.py`, key files lists
      `facility_openings_raw/` and `facility_aliases.json`.

## 6. Smoke test

- [x] Ran forecast locally against the real snapshot
      (`facility_opening_20260420_142744.json`) and the committed
      model. 816 rows (17 facilities × 48h), 341 closed vs 475 open.
- [x] Pools at 03:00 → `is_open=0, occupancy_percent=0`. ✓
- [x] Pools at 12:00 → `is_open=1, occupancy>0` (model predictions
      preserved). ✓
- [x] Ice rink rows every hour → `is_open=0, occupancy_percent=0` across
      the full 48h horizon (`closed_for_season`). ✓
- [x] Zero "No opening hours known" warnings — all 17 facilities matched
      the snapshot.

## 7. Out of scope — confirm before finishing

- [x] No changes to `src/transform.py`, `src/train/train.py`, or
      `models/occupancy_model.pkl`. Model not retrained.
- [x] Forecast CSV schema unchanged — verified via column list
      comparison; only values in `is_open` / `occupancy_percent` differ
      on closed hours.
