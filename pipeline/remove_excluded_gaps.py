"""
Permanently drop the no-ZIP gap polygons listed in excluded_gap_ids.csv
from the map, so a future refresh_all.py rebuild never regenerates and
re-scores them.

These aren't the water-overlap slivers clip_gap_water.py already handles
(that runs on area alone, before any score exists). This list was built
after scoring, from a real methodology bug: spatial_smooth() (scoring.py)
finds queen-contiguity neighbours across the *entire* geometry set,
gap polygons included, and water-clipping shatters a coastline's gap
area into many small adjacent slivers. If one sliver's overlapping census
tract carried a spurious edge-effect PM2.5 estimate, one smoothing pass
spread that value to every other sliver touching it -- 225 of the first
226 candidates found this way had avg_exceedance_days ~0 (near-perfect
air quality) but a percentile score of ~100 (worst in CONUS). See
flag_aq_coastal_slivers.py for the detection method (coastal_frac > 10%
water-clipped AND score > 25 points above real-neighbour mean); the
remaining rows in excluded_gap_ids.csv were user-identified by direct
visual review of the flagged set.

Confirmed before adding any polygon here that removing it can't create a
CONUS coverage hole large enough to fail verify_layers.py's land-coverage
check: even in the worst case where several adjacent excluded slivers
merge into one connected gap, the largest such cluster is ~18 km^2,
comfortably under the 25 km^2 limit.

A polygon here is removed everywhere -- geometry is shared across all 9
categories, so there's no such thing as "delete from Air Quality only".
That's fine: these are tiny fragments of coastal land (median ~0.27 km^2,
max ~25 km^2) contributing little to any category, and the smoothing bug
they expose is itself evidence they shouldn't have survived
clip_gap_water.py's cosmetic cleanup in the first place.

Run: pixi run python pipeline/remove_excluded_gaps.py
  (after clip_gap_water.py, before build_zip_crosswalk.py -- see
  refresh_all.py. For a one-off cleanup of already-scored data, also
  safe to run standalone; it drops matching rows from zip_scores.parquet
  too, if that file exists, then the layers need rewriting.)
"""
import geopandas as gpd
import pandas as pd

from config import PIPELINE_DIR, ZCTA_GEOMETRIES_PATH, ZCTA_RENDER_GEOMETRIES_PATH, ZIP_SCORES_PATH

EXCLUDED_IDS_PATH = PIPELINE_DIR / "excluded_gap_ids.csv"


def main():
    excluded = pd.read_csv(EXCLUDED_IDS_PATH)
    excluded_ids = set(excluded["zcta5"].astype(str))
    print(f"{len(excluded_ids)} excluded gap id(s) loaded from {EXCLUDED_IDS_PATH.name}")

    for path in (ZCTA_GEOMETRIES_PATH, ZCTA_RENDER_GEOMETRIES_PATH):
        gdf = gpd.read_parquet(path)
        before = len(gdf)
        gdf = gdf[~gdf["zcta5"].astype(str).isin(excluded_ids)].reset_index(drop=True)
        removed = before - len(gdf)
        gdf.to_parquet(path)
        print(f"{path.name}: removed {removed} polygon(s), {len(gdf)} remain")

    if ZIP_SCORES_PATH.exists():
        scores = pd.read_parquet(ZIP_SCORES_PATH)
        before = len(scores)
        scores = scores[~scores["zcta5"].astype(str).isin(excluded_ids)].reset_index(drop=True)
        removed = before - len(scores)
        scores.to_parquet(ZIP_SCORES_PATH)
        print(f"{ZIP_SCORES_PATH.name}: removed {removed} row(s), {len(scores)} remain")
    else:
        print(f"{ZIP_SCORES_PATH.name} doesn't exist yet -- nothing to remove there")


if __name__ == "__main__":
    main()
