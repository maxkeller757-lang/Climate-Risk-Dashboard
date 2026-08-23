"""
Drought category: average % time in D0-D4 (any) drought, 2015-2024, from
the U.S. Drought Monitor's county statistics API (sources/usdm.py),
area-weighted onto ZCTAs (spatial.area_weighted_average) using Census
county boundaries as the join geometry (same source as Flood's bbox
tiling, sources/census_counties.py).

Run: pixi run python pipeline/drought.py
"""
import geopandas as gpd

from config import ZCTA_GEOMETRIES_PATH
from scoring import percentile_rank, upsert_zip_scores, write_layer_geojson
from sources.census_counties import load_counties
from sources.usdm import load_avg_drought_pct
from spatial import area_weighted_average

CATEGORY = "drought"
COLOR = "#B8860B"


def main():
    zcta = gpd.read_parquet(ZCTA_GEOMETRIES_PATH)
    counties = load_counties()

    print(f"Querying USDM drought statistics for {len(counties)} counties...")
    avg_pct = load_avg_drought_pct(counties)
    print(f"{len(avg_pct)} counties with drought data")

    raw = area_weighted_average(zcta, counties, "GEOID", avg_pct)
    raw = raw.rename(columns={"value": "avg_drought_pct"})
    raw["avg_drought_pct"] = raw["avg_drought_pct"].fillna(0)
    scored = percentile_rank(raw, raw_col="avg_drought_pct")

    upsert_zip_scores(CATEGORY, scored, raw_col="avg_drought_pct")
    write_layer_geojson(CATEGORY, COLOR)
    print(f"{CATEGORY}: done")


if __name__ == "__main__":
    main()
