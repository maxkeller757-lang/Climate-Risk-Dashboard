"""
Flood category: % of each ZCTA's area inside a FEMA Special Flood Hazard
Area (Zone A/AE/V/VE), queried live from the FEMA NFHL ArcGIS REST service
(see sources/fema_nfhl.py -- no national bulk download exists) and
overlaid against ZCTA polygons via spatial.percent_area_overlay.

This queries ~3,100 county-scoped requests against a live federal service
and can take a while; results are cached per-county so a rerun after a
partial failure only re-fetches what's missing.

Run: pixi run python pipeline/flood.py
"""
import geopandas as gpd

from config import ZCTA_GEOMETRIES_PATH
from scoring import percentile_rank, upsert_zip_scores, write_layer_geojson
from sources.census_counties import load_counties
from sources.fema_nfhl import load_sfha_polygons
from spatial import percent_area_overlay

CATEGORY = "flood"
COLOR = "#1E88A8"


def main():
    zcta = gpd.read_parquet(ZCTA_GEOMETRIES_PATH)
    counties = load_counties()

    print(f"Querying FEMA NFHL SFHA polygons for {len(counties)} counties...")
    sfha = load_sfha_polygons(counties)
    print(f"{len(sfha)} unique SFHA polygons loaded")

    raw = percent_area_overlay(zcta, sfha)
    scored = percentile_rank(raw, raw_col="pct_area")

    upsert_zip_scores(CATEGORY, scored, raw_col="pct_area")
    write_layer_geojson(CATEGORY, COLOR)
    print(f"{CATEGORY}: done")


if __name__ == "__main__":
    main()
