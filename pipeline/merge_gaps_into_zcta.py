"""
Merge specific no-ZIP gap polygons into an adjacent real ZCTA, for gap
polygons found to carry corrupted data of their own -- rather than score
them separately (which would be scoring garbage) or delete them outright
(which would punch a real hole in the map, since these are large enough
that verify_layers.py's hole-size check would reject it), their land
area is absorbed into the neighbouring ZCTA's existing polygon.

The target ZCTA's own score is left completely untouched -- only its
geometry grows. The gap polygon's own id and score row are removed
entirely, since a merged polygon can't also exist as a separate scored
entity.

This differs from remove_excluded_gaps.py in exactly that way: that
script drops a polygon and its area with it (fine for tiny slivers);
this one keeps the area on the map by reassigning it to a real ZCTA that
already has a valid score, so it creates no coverage hole at all.

Run: pixi run python pipeline/merge_gaps_into_zcta.py
  (right after remove_excluded_gaps.py, before anything scores the file)
"""
import geopandas as gpd
import pandas as pd

from config import NO_ZIP_PREFIX, ZCTA_GEOMETRIES_PATH, ZCTA_RENDER_GEOMETRIES_PATH, ZIP_SCORES_PATH

# target zcta5 -> ([gap-polygon id suffixes to merge into it], reason)
MERGES = {
    "03592": (
        ["f69646b075", "9748e5f6e7", "e5f9496737"],
        "User-identified: these three gap polygons carried corrupted data "
        "of their own. ZCTA 03592's existing score is preserved unchanged; "
        "only its geometry grows to absorb their (confirmed-adjacent) area.",
    ),
    "03579": (
        ["30447504da"],
        "Same corrupted-gap-polygon issue as 03592, adjacent to this ZCTA instead.",
    ),
    "04936": (
        ["d6fb5d84ef"],
        "Same corrupted-gap-polygon issue as 03592, adjacent to this ZCTA instead.",
    ),
}


def _merge_one(gdf: gpd.GeoDataFrame, target: str, nozip_ids: list[str]) -> gpd.GeoDataFrame:
    matches = gdf.index[gdf["zcta5"] == target]
    if len(matches) == 0:
        raise RuntimeError(f"merge_gaps_into_zcta: target ZCTA {target} not found")
    idx = matches[0]
    target_geom = gdf.loc[idx, "geometry"]

    gap_rows = gdf[gdf["zcta5"].isin(nozip_ids)]
    missing = set(nozip_ids) - set(gap_rows["zcta5"])
    if missing:
        raise RuntimeError(f"merge_gaps_into_zcta: {missing} not found for merge into {target}")

    merged_geom = gpd.GeoSeries([target_geom, *gap_rows.geometry], crs=gdf.crs).union_all()
    gdf.loc[idx, "geometry"] = merged_geom
    return gdf[~gdf["zcta5"].isin(nozip_ids)].reset_index(drop=True)


def main():
    all_nozip_ids = {f"{NO_ZIP_PREFIX}{n}" for ids, _ in MERGES.values() for n in ids}

    for path in (ZCTA_GEOMETRIES_PATH, ZCTA_RENDER_GEOMETRIES_PATH):
        gdf = gpd.read_parquet(path)
        for target, (suffixes, _reason) in MERGES.items():
            nozip_ids = [f"{NO_ZIP_PREFIX}{n}" for n in suffixes]
            before = len(gdf)
            gdf = _merge_one(gdf, target, nozip_ids)
            print(
                f"{path.name}: merged {len(nozip_ids)} gap polygon(s) into {target} "
                f"({before - len(gdf)} row(s) removed)"
            )
        gdf.to_parquet(path)

    if ZIP_SCORES_PATH.exists():
        scores = pd.read_parquet(ZIP_SCORES_PATH)
        before = len(scores)
        scores = scores[~scores["zcta5"].astype(str).isin(all_nozip_ids)].reset_index(drop=True)
        scores.to_parquet(ZIP_SCORES_PATH)
        print(
            f"{ZIP_SCORES_PATH.name}: removed {before - len(scores)} absorbed gap-polygon "
            "score row(s); target ZCTA scores untouched"
        )
    else:
        print(f"{ZIP_SCORES_PATH.name} doesn't exist yet -- nothing to remove there")


if __name__ == "__main__":
    main()
