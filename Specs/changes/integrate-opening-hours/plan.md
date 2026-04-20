# Implementation Plan: Integrate Opening Hours

Read [proposal.md](./proposal.md) and [architecture.md](./architecture.md)
first.

Tasks are ordered: earlier ones unblock later ones.

## 1. Scaffolding

- [x] Directory `facility_openings_raw/` exists with a `README.md` so the
      scraper has a commit target.
- [x] Workflow `.github/workflows/load_opening_hours.yml` invokes
      `scrape_opening_hours.py` daily at 02:00 UTC.
- [ ] Add a fixture snapshot at
      `tests/fixtures/facility_opening_20260420_040000.json` covering
      at least two facility types, a day with multiple intervals, and one
      entry with `"status": "closed_for_season"`.

## 2. Opening-hours loader

- [ ] Create `src/loaders/opening_hours_loader.py` with:
  - [ ] `load_latest_snapshot(input_dir, aliases) -> dict` that picks the
        most recent `facility_opening_*.json` by filename, reads
        `pool_name` + `facility_type` for each entry, applies alias
        resolution (reuse `resolve_facility_alias` from `transform.py` or
        extract it to a shared helper), and returns
        `{(facility_type, canonical_name): schedule_entry}` where
        `schedule_entry` preserves `status` + `weekly_schedule`.
  - [ ] `is_facility_open(schedules, facility_type, facility_name, dt) ->
        bool | None` implementing the three-state contract from
        [architecture.md](./architecture.md#loader-api). Must iterate **all**
        intervals for the weekday, not stop at the first. Must return
        `False` for any entry with `status == "closed_for_season"`.
  - [ ] Graceful handling for missing dir, missing file, malformed JSON —
        return empty dict and log a warning, same style as other loaders.
- [ ] Add unit tests in `tests/test_opening_hours_loader.py` covering:
  - [ ] Hour inside a single interval → `True`.
  - [ ] Hour at the `close_time` boundary → `False` (half-open interval).
  - [ ] Facility present but no intervals that day → `False`.
  - [ ] Facility with `status == "closed_for_season"` → `False` on every
        day of the week.
  - [ ] Facility missing from snapshot → `None`.
  - [ ] Alias resolution applied (old `pool_name` in snapshot, canonical
        queried).
  - [ ] Day with two intervals, hour falls in the second one → `True`.

## 3. Forecast overlay

- [ ] In `src/forecast/forecast.py`:
  - [ ] Add `--opening-hours-dir` CLI flag
        (default `../../facility_openings_raw`).
  - [ ] Load aliases (same helper `transform.py` uses).
  - [ ] Call `load_latest_snapshot` once at startup; log snapshot filename
        and facility count.
  - [ ] In `generate_forecasts`, per (facility, hour) compute
        `is_open_now = is_facility_open(...)` and apply the precedence table
        from
        [architecture.md](./architecture.md#overlay-semantics):
    - `False` → `is_open = 0`, `occupancy_percent = 0.0`.
    - `True` → `is_open = 1`, keep model prediction.
    - `None` → `is_open = "NULL"`, keep model prediction, log warning once
      per unknown facility.
- [ ] Add/extend tests for `forecast.py`:
  - [ ] With a fixture snapshot, verify a known-closed hour emits `is_open=0`
        and `occupancy_percent=0.0`.
  - [ ] With a snapshot missing a facility, verify `is_open=NULL` and a
        warning is logged.

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

- [ ] Update `README.md`:
  - [ ] Add `facility_openings_raw/` to the repository-structure tree.
  - [ ] Add a new "Opening Hours" subsection under **Data Formats** with
        the JSON shape (including the `status` field).
  - [ ] Add `load_opening_hours.yml` to the automation-schedule table.
  - [ ] Update the pipeline overview ASCII diagram to include the new
        source.
- [ ] Update `Specs/03_FORECAST_FILE_FORMAT.md`:
  - [ ] Change the `is_open` row for forecast to state the deterministic
        overlay behavior (`1` / `0` / `NULL` with meanings).
  - [ ] Note that `occupancy_percent = 0` when `is_open = 0`.
- [ ] Add a note in `CLAUDE.md` listing the new raw directory under
      repository structure.

## 6. Smoke test

- [ ] From repo root: run the existing forecast locally with a real
      snapshot already present in `facility_openings_raw/` (downloaded
      via `git pull` after the daily workflow runs), inspect a few rows of
      `datasets/occupancy_forecast.csv`, and confirm a pool's 03:00 hour
      is `is_open=0, occupancy_percent=0`.
- [ ] Confirm the ice rink rows stay `is_open=0` throughout the 48h
      horizon while `status == "closed_for_season"` in the snapshot.

## 7. Out of scope — confirm before finishing

- [ ] Double-check no changes slipped into `src/transform.py`,
      `src/train/train.py`, or `models/occupancy_model.pkl`. The model must
      not be retrained as part of this change.
- [ ] Double-check the forecast CSV schema has the **same columns in the
      same order** as before — only values change for closed hours.
