"""
Air Quality category: average days per year with county mean PM2.5 above
35.4 ug/m^3 (the point where the 24-hour AQI passes 100 into "Unhealthy
for Sensitive Groups"), 2015-2021, from the CDC/EPA fused daily county
surface (sources/cdc_pm25.py), area-weighted onto ZCTAs.

Window note: this category covers 2015-2021 rather than the project's
2015-2024, because the source dataset ends 31 Oct 2022 and a partial year
would undercount. Seven whole years is still a stable climatology for a
metric this noisy year-to-year (wildfire smoke drives big single-year
swings).

Run: pixi run python pipeline/air_quality.py
"""
import geopandas as gpd

from config import ZCTA_GEOMETRIES_PATH
from scoring import percentile_rank, upsert_zip_scores, write_layer_geojson
from sources.cdc_pm25 import load_exceedance_days
from sources.census_counties import load_counties_legacy_ct
from spatial import area_weighted_average

CATEGORY = "air_quality"
COLOR = "#9A9A94"


def main():
    zcta = gpd.read_parquet(ZCTA_GEOMETRIES_PATH)
    # Legacy CT counties: this source covers 2015-2021, before Connecticut
    # switched to Planning Regions, so it keys on the old county FIPS.
    counties = load_counties_legacy_ct()

    print("Querying CDC/EPA fused daily county PM2.5...")
    days = load_exceedance_days()

    covered = counties["GEOID"].isin(days.index).mean()
    print(f"{len(days)} counties with PM2.5 data; {100 * covered:.1f}% of CONUS counties covered")
    if covered < 0.95:
        raise RuntimeError(
            f"Only {100 * covered:.1f}% of CONUS counties have PM2.5 data -- "
            "too sparse to area-weight onto ZCTAs without heavy interpolation."
        )

    raw = area_weighted_average(zcta, counties, "GEOID", days)
    raw = raw.rename(columns={"value": "avg_exceedance_days"})

    missing = raw["avg_exceedance_days"].isna().sum()
    if missing:
        # Only ZCTAs whose geometry overlaps no county at all (offshore
        # slivers); fill_nozip_scores interpolates these from neighbours.
        print(f"{missing} ZCTA(s) matched no county -- left NaN for neighbour interpolation")

    scored = percentile_rank(raw, raw_col="avg_exceedance_days")

    upsert_zip_scores(CATEGORY, scored, raw_col="avg_exceedance_days")
    write_layer_geojson(CATEGORY, COLOR)
    print(f"{CATEGORY}: done")


if __name__ == "__main__":
    main()
