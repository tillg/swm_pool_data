# SWM Pool Occupancy Data

Real-time occupancy data from Munich's public swimming pools and saunas, collected every 15 minutes via GitHub Actions.

## Data Source

Data is scraped from [Stadtwerke München (SWM)](https://www.swm.de/baeder/auslastung) using the [swm_pool_scraper](https://github.com/tillg/swm_pool_scraper) tool.

## Facilities Tracked

**Swimming Pools:**
- Bad Giesing-Harlaching
- Cosimawellenbad
- Michaelibad
- Müller'sches Volksbad
- Nordbad
- Südbad
- Westbad

**Saunas:**
- Cosimawellenbad
- Dantebad
- Michaelibad
- Nordbad
- Südbad
- Westbad

## Data Format

Each JSON file in `pool_scrapes_raw/` contains:

```json
{
  "scrape_timestamp": "2026-01-16T10:30:41.315123",
  "scrape_metadata": {
    "total_facilities": 13,
    "pools_count": 7,
    "saunas_count": 6,
    "hour": 10,
    "day_of_week": 3,
    "is_weekend": false
  },
  "pools": [...],
  "saunas": [...],
  "summary": {
    "avg_pool_occupancy": 76.4,
    "busiest_pool": "Südbad",
    "quietest_pool": "Cosimawellenbad"
  }
}
```

Each facility entry includes:
- `pool_name` - Facility name
- `occupancy_percent` - Current free capacity (0-100%)
- `current_visitors` - Number of people currently inside
- `max_capacity` - Maximum allowed visitors
- `facility_type` - "pool" or "sauna"

## Collection Schedule

Data is collected automatically every 15 minutes via GitHub Actions (~96 data points per day).

## Use Cases

- Machine learning models for predicting pool occupancy
- Historical analysis of usage patterns
- Planning visits to avoid crowds

## Related

- [swm_pool_scraper](https://github.com/tillg/swm_pool_scraper) - The scraping tool
