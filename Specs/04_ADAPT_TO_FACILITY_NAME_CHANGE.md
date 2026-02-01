# Adapt to Facility Name Change

## Problem

On January 19, 2026, SWM changed sauna naming from "Dantebad Sauna" to just "Dantebad" (dropping the " Sauna" suffix). The transform pipeline now treats these as separate facilities, fragmenting the time series and breaking ML training.

## Affected Facilities

| Old Name (≤Jan 18) | New Name (≥Jan 19) |
|--------------------|-------------------|
| Cosimawellenbad Sauna | Cosimawellenbad |
| Dantebad Sauna | Dantebad |
| Michaelibad Sauna | Michaelibad |
| Nordbad Sauna | Nordbad |
| Südbad Sauna | Südbad |
| Westbad Sauna | Westbad |

Note: Müller'sches Volksbad sauna is new from Jan 19 (no aliasing needed).

## Solution

Create a static alias mapping in `src/config/facility_aliases.json` (committed to repo). The key includes facility type to avoid ambiguity since names like "Nordbad" exist as both pool and sauna.

Key format: `{facility_type}:{old_name}` → `{canonical_name}`

Facility type is read from the raw JSON scrape data, so aliasing happens after type is already known. Unknown facility names pass through unchanged (new facilities).

## Implementation

1. **Create `src/config/facility_aliases.json`** with the sauna mappings

2. **Modify `src/transform.py`**:
   - Load aliases at start of `transform()`
   - Apply alias lookup in `load_pool_data()` after extracting `facility_name` and `facility_type` from raw JSON

3. **Add unit test** for alias resolution logic

4. **Regenerate data**:
   - Delete `datasets/occupancy_historical.csv`
   - Run transform to rebuild from raw JSON
   - Verify `facility_types.json` only contains canonical names

## Validation

- No "* Sauna" entries in output CSV for sauna facility names
- Continuous time series for each sauna across the Jan 19 boundary
- 6 saunas before Jan 19, 7 from Jan 19 onwards (Müller'sches Volksbad added)
