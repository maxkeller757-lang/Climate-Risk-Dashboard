"""
Wildfire category: 70% zonal-mean USFS Wildfire Hazard Potential (WHP,
2020 version, point-in-time model -- no 2015-2024 windowing applies to it)
+ 30% count of MTBS historical burn perimeters intersecting the ZCTA,
2015-2024.

As with Seismic, the two components are percentile-ranked independently
first, then blended -- WHP's index units and a raw burn count aren't
comparable on their own scale. WHP as primary / MTBS as supplement (70/30)
mirrors the project brief's framing of WHP as the primary source and MTBS
as the "historical supplement."

Run: pixi run python pipeline/wildfire.py
"""
import geopandas as gpd

from config import RAW_DIR, ZCTA_GEOMETRIES_PATH
from scoring import percentile_rank, upsert_zip_scores, write_layer_geojson
from sources.mtbs import load_burn_perimeters
from spatial import intersect_count, raster_zonal_mean

CATEGORY = "wildfire"
COLOR = "#D32F2F"
WHP_WEIGHT = 0.7
MTBS_WEIGHT = 0.3
WHP_RASTER_PATH = RAW_DIR / "WHP_CONUS" / "WHP_CONUS.tif"


def main():
    zcta = gpd.read_parquet(ZCTA_GEOMETRIES_PATH)

    print("Computing zonal-mean Wildfire Hazard Potential...")
    whp = raster_zonal_mean(zcta, WHP_RASTER_PATH)
    # WHP uses large negative sentinel values for water/non-burnable/no-data
    # pixels (not present in the visible index range); treat as 0 hazard,
    # not missing.
    whp.loc[whp["mean"] < 0, "mean"] = 0
    whp["mean"] = whp["mean"].fillna(0)
    whp_scored = percentile_rank(whp, raw_col="mean", score_col="whp_score")

    print("Loading MTBS historical burn perimeters (2015-2024)...")
    burns = load_burn_perimeters()
    print(f"{len(burns)} burn perimeters loaded")
    burn_counts = intersect_count(zcta, burns)
    burn_scored = percentile_rank(burn_counts, raw_col="count", score_col="mtbs_score")

    combined = whp_scored.merge(burn_scored[["zcta5", "mtbs_score"]], on="zcta5")
    combined["blended"] = (
        WHP_WEIGHT * combined["whp_score"] + MTBS_WEIGHT * combined["mtbs_score"]
    )

    scored = percentile_rank(combined, raw_col="blended")
    upsert_zip_scores(CATEGORY, scored, raw_col="blended")
    write_layer_geojson(CATEGORY, COLOR)
    print(f"{CATEGORY}: done")


if __name__ == "__main__":
    main()
