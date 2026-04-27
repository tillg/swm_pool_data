# Bug: `is_open` is always `1` in `occupancy_historical.csv`

**Status:** Implemented (2026-04-27)
**Reported by:** swm_pool_viewer integration work, 2026-04-27
**Severity:** Medium — historical rows carry incorrect schedule information; downstream consumers cannot detect open/close transitions from the historical CSV.

## Resolution

`src/transform.py` now applies the same deterministic opening-hours
overlay the forecast pipeline uses:

- New helper `apply_opening_hours_overlay(df, schedules)` reuses
  `src/loaders/opening_hours_loader.py`. Closed rows get `is_open=0`
  and `occupancy_percent=0.0`; open rows get `is_open=1`; rows for
  facilities missing from the snapshot are left untouched.
- Called once per transform run on the **whole** combined frame, so
  the existing CSV is backfilled in place. Idempotent.
- New `--opening-hours-dir` CLI flag (default `facility_openings_raw`).

After the first run on 2026-04-27:

| Metric | Before | After |
|--------|--------|-------|
| `is_open=1` rows | 98 491 (100 %) | 64 259 (65 %) |
| `is_open=0` rows | 0 | 34 249 (35 %) |
| Facility-days with at least one `is_open=0` | 0 | 1 722 (all) |
| `is_open=0` rows with `occupancy_percent != 0` | n/a | 0 |
| Ice rink (`closed_for_season`) rows correctly closed | 0 | 5 597 (all) |

The verification list at the bottom of this proposal is satisfied by
the patched transform.

## Symptom

In `datasets/occupancy_historical.csv`, the `is_open` column is `1`
on **every** row, including hours when the facility is provably
scheduled closed (e.g., 00:00–07:00 for pools that open at 08:00).
There are no `is_open=0` historical rows and no `0↔1` transitions
ever, regardless of weekday or time.

`datasets/occupancy_forecast.csv` does not exhibit this — it
correctly carries `is_open=0` outside scheduled hours, matching the
deterministic opening-hours overlay introduced by
[`integrate-opening-hours`](../integrate-opening-hours/proposal.md).

## Evidence (snapshot 2026-04-27)

For `Bad Giesing-Harlaching` / `pool` (scheduled Sat–Mon 08:00–18:00,
Tue–Fri 08:00–21:00 per `facility_openings_raw/facility_opening_20260425_051010.json`):

### Historical rows on Sat 2026-04-25 — `is_open` per hour

| Hour | `is_open=1` rows | `is_open=0` rows |
|------|------------------|------------------|
| 00 | 3 | 0 |
| 01 | 2 | 0 |
| 02 | 2 | 0 |
| 03 | 1 | 0 |
| 04 | 1 | 0 |
| 05 | 1 | 0 |
| 06 | 1 | 0 |
| 07 | 1 | 0 |
| … (08–17 expected open) | 1–3 | 0 |
| 18–23 | 2–3 | 0 |

Every overnight hour reports `is_open=1`, including 18:00–23:00 when
the pool is closed.

Sample rows (filtered):

```
2026-04-25T00:15:09+02:00, …, occupancy_percent=100.0, is_open=1
2026-04-25T03:42:28+02:00, …, occupancy_percent=100.0, is_open=1
2026-04-25T22:46:06+02:00, …, occupancy_percent=100.0, is_open=1
2026-04-25T23:47:33+02:00, …, occupancy_percent=100.0, is_open=1
```

### Compare with forecast on Mon 2026-04-27

```
2026-04-27T04:00:00+02:00, …, occupancy_percent=0.0, is_open=0   ← correctly closed
2026-04-27T05:00:00+02:00, …, occupancy_percent=0.0, is_open=0
2026-04-27T06:00:00+02:00, …, occupancy_percent=0.0, is_open=0
2026-04-27T07:00:00+02:00, …, occupancy_percent=0.0, is_open=0
2026-04-27T08:00:00+02:00, …, occupancy_percent=90.0, is_open=1   ← opens
…
2026-04-27T17:00:00+02:00, …, occupancy_percent=78.1, is_open=1
2026-04-27T18:00:00+02:00, …, occupancy_percent=0.0, is_open=0   ← closes
```

The forecast properly applies the schedule; the historical does not.

### Cross-source inconsistency in the overlap region

The overlap (forecast covers from ~07:00 today onward; historical
also exists for the same minutes) shows the two sources actively
contradicting each other on the same `(facility, hour)`:

```
2026-04-27T05:00:00+02:00 forecast    is_open=0   ← schedule says closed
2026-04-27T05:16:49+02:00 historical  is_open=1   ← but historical says open
2026-04-27T06:00:00+02:00 forecast    is_open=0
2026-04-27T06:38:47+02:00 historical  is_open=1
2026-04-27T07:00:00+02:00 forecast    is_open=0
2026-04-27T08:00:00+02:00 forecast    is_open=1   ← schedule says open
```

Any consumer that walks the merged stream looking for transitions
sees ghost flips at every data-source switch, not real schedule
events.

## Expected behavior

`is_open` in historical rows should reflect the same deterministic
opening-hours overlay as forecast rows, per the contract documented
in
[`integrate-opening-hours`](../integrate-opening-hours/proposal.md):

| `is_open` | Meaning |
|-----------|---------|
| `1` | Facility scheduled open at this hour |
| `0` | Facility scheduled closed at this hour (sentinel; `occupancy_percent=0` is **not** a real reading) |
| `null` | Facility missing from the opening-hours snapshot |

Specifically: a historical row at `2026-04-25T03:42:28+02:00` for a
pool whose Saturday schedule is `08:00–18:00` should carry
`is_open=0`, not `is_open=1`.

## Suspected cause

The opening-hours overlay step appears to run on the forecast emit
path only, not on the historical compilation path. Either:

1. The overlay function isn't called when materializing
   `occupancy_historical.csv`, or
2. It is called but the historical compiler passes `is_open=1` as a
   default and the overlay only *flips to 0* when it has a schedule
   entry, while never being invoked for historical rows in the
   first place — leaving the default in place.

The fix is presumably the same one shape as the forecast path:
look up `(facility, weekday, hour)` in the latest
`facility_opening_*.json` weekly_schedule and set `is_open` to
`0` outside scheduled windows.

## Impact downstream

`swm_pool_viewer` change `chart-opening-hours-markers` (in progress
at the time of writing) wanted to detect open/close transitions
from the merged CSV stream as the cheapest source of truth (no
extra fetch). With this bug, that path is unusable — historical
shows no transitions and the cross-source overlap region produces
phantom transitions every day.

The viewer's workaround is to fetch `facility_openings_raw/*.json`
directly. That works but introduces a new data dependency and a
latest-file-discovery problem that wouldn't exist if historical
`is_open` were correct.

## Out of scope (recommendations, not requirements)

These would also help downstream consumers but are independent of
the bug fix:

- Publish a stable `facility_opening_latest.json` alias (symlink
  or daily copy) so consumers can fetch the latest schedule via
  `raw.githubusercontent.com` without a GitHub directory listing.
- Backfill the corrected `is_open` into existing historical rows
  rather than only fixing forward — depends on how much history
  matters for downstream viz.

## Verification

Once fixed, the following should hold for any historical CSV:

1. For every `(facility, day)` where the facility is in the
   opening-hours snapshot, the set of `is_open=1` hours matches the
   weekly schedule's open intervals for that weekday.
2. There exists at least one `is_open=0` historical row per
   facility per day (the pre-opening or post-closing hours).
3. A walk over the merged historical+forecast stream sorted by
   `(facility, timestamp)` produces `0↔1` transitions only at
   genuine schedule boundaries, never at data-source boundaries.
