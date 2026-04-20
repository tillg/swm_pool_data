# facility_openings_raw

Daily snapshots of SWM facility opening hours, written by the
`Load Opening Hours` GitHub Actions workflow.

- **Cadence**: once per day
- **Writer**: `tillg/swm_pool_scraper` — `python scrape_opening_hours.py`
- **Filename**: `facility_opening_YYYYMMDD_HHMMSS.json` (Europe/Berlin time)
- **Shape**: one file per run; array of 17 entries keyed by
  `(pool_name, facility_type)`; each entry carries `status` of `"open"` or
  `"closed_for_season"` plus a parsed `weekly_schedule`.

If a run fails, no file is written — the failed GH Actions run is the
alert. Check the workflow's logs and file an issue upstream if SWM's
markup has drifted.
