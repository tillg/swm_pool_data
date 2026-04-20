# Implementation Plan: Integrate Opening Hours

Read [proposal.md](./proposal.md) and [architecture.md](./architecture.md)
first.

Tasks are ordered: earlier ones unblock later ones.

## 1. Scaffolding

- [ ] Create empty `pool_opening_raw/` directory with a `.gitkeep` file so the
      scraper has a commit target.
- [ ] Add a fixture snapshot at
      `tests/fixtures/pool_opening_20260116_180836.json` covering at least
      two facility types and a day with multiple intervals, matching the
      schema in [architecture.md](./architecture.md#data-format-pool_opening_json).

## 2. Opening-hours loader

- [ ] Create `src/loaders/opening_hours_loader.py` with:
  - [ ] `load_latest_snapshot(input_dir, aliases) -> dict` that picks the
        most recent `pool_opening_*.json` by filename, applies alias
        resolution (reuse `resolve_facility_alias` from `transform.py` or
        extract it to a shared helper), and returns
        `{(facility_type, facility_name): weekly_schedule}`.
  - [ ] `is_facility_open(schedules, facility_type, facility_name, dt) ->
        bool | None` implementing the three-state contract from
        [architecture.md](./architecture.md#loader-api). Must iterate **all**
        intervals for the weekday, not stop at the first.
  - [ ] Graceful handling for missing dir, missing file, malformed JSON —
        return empty dict and log a warning, same style as other loaders.
- [ ] Add unit tests in `tests/test_opening_hours_loader.py` covering:
  - [ ] Hour inside a single interval → `True`.
  - [ ] Hour at the `close_time` boundary → `False` (half-open interval).
  - [ ] Facility present but no intervals that day → `False`.
  - [ ] Facility missing from snapshot → `None`.
  - [ ] Alias resolution applied (old name in snapshot, canonical queried).
  - [ ] Day with two intervals, hour falls in the second one → `True`.

## 3. Forecast overlay

- [ ] In `src/forecast/forecast.py`:
  - [ ] Add `--opening-hours-dir` CLI flag (default `../../pool_opening_raw`).
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

- [ ] Create `.github/workflows/load_opening_hours.yml`:
  - [ ] Cron: daily at `04:45 UTC` (before the existing forecast run).
  - [ ] Manual trigger: `workflow_dispatch`.
  - [ ] Invoke the external opening-hours scraper (placeholder step — mirror
        how `scrape.yml` invokes the pool scraper).
  - [ ] Commit any new `pool_opening_raw/pool_opening_*.json` files, using
        the same "only add specific files" style as `scrape.yml` to avoid
        sweeping up unrelated changes (see
        [CLAUDE.md](../../../CLAUDE.md#git-commit-guidelines)).
- [ ] Verify `.github/workflows/forecast.yml` still runs at 05:00 UTC so it
      picks up the fresh snapshot. If the two are too tight, either push
      opening-hours earlier or add a `workflow_run` dependency from
      opening-hours → forecast.

## 5. Documentation

- [ ] Update `README.md`:
  - [ ] Add `pool_opening_raw/` to the repository-structure tree.
  - [ ] Add a new "Opening Hours" subsection under **Data Formats** with the
        JSON shape.
  - [ ] Add `load_opening_hours.yml` to the automation-schedule table.
  - [ ] Update the pipeline overview ASCII diagram to include the new source.
- [ ] Update `Specs/03_FORECAST_FILE_FORMAT.md`:
  - [ ] Change the `is_open` row for forecast to state the deterministic
        overlay behavior (`1` / `0` / `NULL` with meanings).
  - [ ] Note that `occupancy_percent = 0` when `is_open = 0`.
- [ ] Add a note in `CLAUDE.md` listing the new raw directory under
      repository structure.

## 6. Smoke test

- [ ] From repo root: run the existing forecast locally with the fixture
      snapshot copied into `pool_opening_raw/`, inspect a few rows of
      `datasets/occupancy_forecast.csv`, and confirm a pool's 03:00 hour is
      `is_open=0, occupancy_percent=0`.
- [ ] Remove the fixture from `pool_opening_raw/` before committing (leave
      only `.gitkeep` for real data).

## 7. Out of scope — confirm before finishing

- [ ] Double-check no changes slipped into `src/transform.py`,
      `src/train/train.py`, or `models/occupancy_model.pkl`. The model must
      not be retrained as part of this change.
- [ ] Double-check the forecast CSV schema has the **same columns in the
      same order** as before — only values change for closed hours.
