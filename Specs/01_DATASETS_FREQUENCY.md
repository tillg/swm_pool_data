# Dataset Frequency

## Goal

Run the transform pipeline every time new raw data is added, instead of once daily.

## Current State

- `scrape.yml` runs every 15 minutes, commits new pool data
- `transform.yml` runs once daily at 06:00 UTC

## Solution

Modify `transform.yml` to trigger on every push to raw data directories:

```yaml
on:
  push:
    paths:
      - 'pool_scrapes_raw/**'
      - 'weather_raw/**'
  workflow_dispatch:

concurrency:
  group: transform-pipeline
  cancel-in-progress: true
```

**Key behaviors:**

- Triggers on any push containing pool or weather data changes
- Concurrency group ensures only one transform runs at a time
- `cancel-in-progress: true` cancels any running transform when new data arrives, so the latest data always gets processed
- Remove the daily schedule trigger (no longer needed)
- Keep `workflow_dispatch` for manual runs

## Implementation

1. Update `transform.yml` with the trigger and concurrency settings above
2. Remove the `schedule` trigger
