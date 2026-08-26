"""
Air Quality category: average days per year with census-tract mean PM2.5
above 35.4 ug/m^3 (the point where the 24-hour AQI passes 100 into
"Unhealthy for Sensitive Groups"), 2016-2020, from the CDC/EPA fused
daily tract surface (sources/cdc_pm25.py), area-weighted onto ZCTAs.

Window note: this category covers 2016-2020 rather than the project's
2015-2024, because CDC's tract-level release of this data doesn't extend
as far as its county-level release. Five whole years is still a stable
climatology for a metric this noisy year-to-year (wildfire smoke drives
big single-year swings).

Tract, not county: an earlier version of this category apportioned onto
ZCTAs from county-level PM2.5 values. That data was never a human-report
signal -- it's the same monitor+model fused surface as today -- but
county bucketing (3,109 counties, some spanning hundreds of km) created a
real granularity artifact: two ZCTAs a few miles apart on opposite sides
of a county line could get very different scores from an otherwise
continuous field, heavily amplified by percentile_rank()'s sensitivity
near this metric's mass of zeros (most ZCTAs average under a day a year
above the threshold). Tract-level apportionment (95,072 tracts, ~30x
finer) shrinks that artifact directly. It doesn't eliminate it -- tract
lines are still administrative boundaries -- so this still runs
scoring.spatial_smooth before ranking, unlike Winter Weather, whose
zone-boundary artifact was a fake signal removed by changing the data
source, not by smoothing.

This category deliberately does not detrend against population density
the way severe_convective does: dense-urban PM2.5 elevation here is a
real physical signal (traffic and industrial sources concentrate where
people do), not a reporting-density artifact, so it should come through
undamped.

Run: pixi run python pipeline/air_quality.py
"""
import geopandas as gpd

from config import ZCTA_GEOMETRIES_PATH
from scoring import percentile_rank, spatial_smooth, upsert_zip_scores, write_layer_geojson
from sources.cdc_pm25 import load_exceedance_days
from sources.census_tracts import load_tracts
from spatial import area_weighted_average

CATEGORY = "air_quality"
COLOR = "#9A9A94"


def main():
    zcta = gpd.read_parquet(ZCTA_GEOMETRIES_PATH)
    tracts = load_tracts()

    print("Querying CDC/EPA fused daily tract PM2.5...")
    days = load_exceedance_days()

    covered = tracts["GEOID"].isin(days.index).mean()
    print(f"{len(days)} tracts with PM2.5 data; {100 * covered:.1f}% of CONUS tracts covered")
    if covered < 0.95:
        raise RuntimeError(
            f"Only {100 * covered:.1f}% of CONUS tracts have PM2.5 data -- "
            "too sparse to area-weight onto ZCTAs without heavy interpolation."
        )

    raw = area_weighted_average(zcta, tracts, "GEOID", days)
    raw = raw.rename(columns={"value": "avg_exceedance_days"})

    missing = raw["avg_exceedance_days"].isna().sum()
    if missing:
        # Only ZCTAs whose geometry overlaps no tract at all (offshore
        # slivers); fill_nozip_scores interpolates these from neighbours.
        print(f"{missing} ZCTA(s) matched no tract -- left NaN for neighbour interpolation")

    print("Smoothing with neighbouring ZCTAs to soften county-line cliffs...")
    smoothed = spatial_smooth(zcta, raw, raw_col="avg_exceedance_days")
    scored = percentile_rank(smoothed, raw_col="spatially_smoothed")

    upsert_zip_scores(CATEGORY, scored, raw_col="avg_exceedance_days")
    write_layer_geojson(CATEGORY, COLOR)
    print(f"{CATEGORY}: done")


if __name__ == "__main__":
    main()
