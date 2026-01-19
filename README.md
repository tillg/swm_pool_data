# SWM Pool Occupancy Data

Real-time occupancy data from Munich's public SWM facilities (pools, saunas, ice rinks), collected every 15 minutes via GitHub Actions.

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

**Ice Rinks:**
- Prinzregentenstadion - Eislaufbahn

## Repository Structure

```
swm_pool_data/
├── pool_scrapes_raw/          # Raw pool occupancy JSON (every 15 min)
├── weather_raw/               # Hourly weather data from Open-Meteo
├── holidays/                  # Public holidays and school vacations
│   ├── public_holidays.json   # Bavarian public holidays
│   └── school_holidays.json   # Bavarian school vacations
├── datasets/                  # ML-ready transformed data
│   └── occupancy_features.csv
├── src/
│   ├── loaders/
│   │   ├── weather_loader.py  # Fetches weather from Open-Meteo
│   │   └── holiday_loader.py  # Generates/loads holiday data
│   └── transform.py           # Merges all data into ML features
└── .github/workflows/
    ├── scrape.yml             # Pool scraping (every 15 min) → triggers transform
    ├── load_weather.yml       # Weather fetching (daily 05:00 UTC) → triggers transform
    └── transform.yml          # Data transformation (after scrape or weather update)
```

## Data Formats

### Raw Pool Data

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

### Transformed Dataset

The `datasets/occupancy_features.csv` contains ML-ready features:

| Column | Description |
| ------ | ----------- |
| `timestamp` | ISO 8601 timestamp |
| `pool_name` | Facility name |
| `facility_type` | "pool", "sauna", or "ice_rink" |
| `occupancy_percent` | Free capacity (0-100%) |
| `is_open` | 0 or 1 |
| `hour` | Hour of day (0-23) |
| `day_of_week` | 0=Monday, 6=Sunday |
| `month` | Month (1-12) |
| `is_weekend` | 0 or 1 |
| `is_holiday` | Public holiday (0 or 1) |
| `is_school_vacation` | School vacation (0 or 1) |
| `temperature_c` | Air temperature in °C |
| `precipitation_mm` | Precipitation in mm |
| `weather_code` | WMO weather code |
| `cloud_cover_percent` | Cloud cover percentage |

## Local Development

### Setup

```bash
# Create virtual environment
python3 -m venv .venv
source .venv/bin/activate

# Install dependencies
pip install -r requirements.txt
```

### Syncing with GitHub

Since GitHub Actions updates this repo every 15 minutes with new data, your local copy will quickly become outdated. Here's how to stay in sync:

**Get the latest data (no local changes):**

```bash
git pull
```

**If you're in the middle of editing (not done yet):**

```bash
git stash            # Temporarily hide your work-in-progress
git pull             # Get the latest from GitHub
git stash pop        # Bring your work-in-progress back
```

**If you're done and want to save & upload your changes:**

```bash
git add .                              # Stage all your changes
git commit -m "Describe your change"   # Save to git history
git pull --rebase                      # Get latest, put your commit on top
git push                               # Upload to GitHub
```

**If you get merge conflicts:** This can happen if you edited a file that was also changed on GitHub. Git will tell you which files have conflicts. Open them, look for the `<<<<<<<` markers, decide which version to keep, remove the markers, then:

```bash
git add .
git commit -m "Resolved merge conflicts"
git push
```

### Running the Weather Loader

Fetches 7 days of historical and 7 days of forecast weather data from Open-Meteo:

```bash
# From repository root
python src/loaders/weather_loader.py --output-dir weather_raw
```

Options:
- `--output-dir` - Output directory (default: `weather_raw`)
- `--past-days` - Historical days to fetch (default: 7)
- `--forecast-days` - Forecast days to fetch (default: 7)

### Running the Holiday Loader

Generates Bavarian public holidays using the `holidays` Python package:

```bash
# From repository root
python src/loaders/holiday_loader.py --output holidays/public_holidays.json --years 2025 2026 2027
```

Options:
- `--output` - Output file path (default: `holidays/public_holidays.json`)
- `--years` - Years to generate (default: 2025 2026 2027)

School holidays are manually maintained in `holidays/school_holidays.json` from the official Bavarian calendar.

### Running the Transform Pipeline

Merges pool occupancy, weather, and holiday data into a single ML-ready CSV:

```bash
# From src directory
cd src
python transform.py
```

Or with explicit paths:

```bash
cd src
python transform.py \
  --pool-dir ../pool_scrapes_raw \
  --weather-dir ../weather_raw \
  --holiday-dir ../holidays \
  --output ../datasets/occupancy_features.csv
```

The transform:
1. Loads all pool JSON files from `pool_scrapes_raw/`
2. Loads weather data and aligns by hour
3. Adds holiday and school vacation flags
4. Deduplicates and appends to existing CSV
5. Outputs to `datasets/occupancy_features.csv`

## Collection Schedule

| Workflow | Schedule | Description |
| -------- | -------- | ----------- |
| Pool scraping | Every 15 min | ~96 data points per day, triggers transform |
| Weather loading | Daily 05:00 UTC | 14 days of hourly weather, triggers transform |
| Data transform | After scrape/weather | Merges all features into CSV |

## Use Cases

- Machine learning models for predicting pool occupancy
- Historical analysis of usage patterns
- Planning visits to avoid crowds
- Correlating weather with pool attendance

## Related

- [swm_pool_scraper](https://github.com/tillg/swm_pool_scraper) - The scraping tool
