# Data Irregularities Detection

## Goal

Proactively detect upstream data changes (like the Jan 2026 sauna name change) before they break the pipeline. This complements `04_ADAPT_TO_FACILITY_NAME_CHANGE.md` which handles known changes via `facility_aliases.json` - this spec catches **unknown** changes early.

## Checks

### Raw Scrape Data (`check_raw_scrapes.py`)

| Check | Description |
|-------|-------------|
| Missing facility | Facility not seen for 2+ hours (compared to last 30 days) |
| New facility | Facility appears that wasn't in historical data |
| Capacity change | Capacity differs from historical |
| Scrape gaps | Gap of 2+ hours between scrapes |

### Compiled Data (`check_compiled_data.py`)

| Check | Description |
|-------|-------------|
| New facility type | A `facility_type` value appears that wasn't seen before |
| Missing facility type | A `facility_type` that existed historically is no longer present |
| Occupancy > 100% | Invalid occupancy value |
| Extended zero occupancy | Facility at 0% for 8+ hours during daytime (6:00-22:00) |

## Files

```
src/checks/
├── check_raw_scrapes.py      # Checks against pool_scrapes_raw/
└── check_compiled_data.py    # Checks against occupancy_historical.csv
src/tests/
└── test_checks.py            # Unit tests for all check functions
.github/workflows/
└── detect_irregularities.yml # Daily run at 19:00 UTC
```

## Output

Creates a GitHub Issue with label `data-irregularity` when irregularities are found. Issues include affected facilities and suggested actions.
