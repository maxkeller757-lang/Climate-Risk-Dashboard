"""
Fill in any polygon still missing hazard scores by interpolating from its
neighbours -- a safety net that runs after all the category modules.

Most no-ZIP gap polygons (tidal marsh, barrier islands, unaddressed inland
parcels -- see fetch_zcta_geometries.py) do NOT need this: they are real
geometry, so the category modules score them directly and those computed
values are strictly better than any interpolation. What this catches is
the residue -- polygons where a category legitimately has no data to give,
typically raster categories whose source excludes water and marsh (WHP has
no value over open water, so a marsh polygon can come back NaN).

Those leftovers still need a number, because a polygon with a null score
renders at the bottom of the colour ramp and is indistinguishable from a
hole in the map. Interpolating from the immediate surroundings is the
right estimate: a marsh island off Charleston carries essentially the same
exposure as the Charleston ZCTAs it touches.

Interpolation is a shared-boundary-length-weighted mean of the adjacent
real ZCTAs' scores -- weighting by how much boundary each neighbor shares
(rather than a flat mean) keeps a long coastal ZCTA from being outvoted by
a couple of tiny ones that happen to clip a corner. Gap pieces that touch
no real ZCTA at all (detached offshore islands) fall back to the single
nearest real ZCTA.

Run: pixi run python pipeline/fill_nozip_scores.py
  (after every category module, and before pipeline/composite.py)
"""
import geopandas as gpd
import pandas as pd
import shapely

from config import EQUAL_AREA_CRS, NO_ZIP_PREFIX, ZCTA_GEOMETRIES_PATH, ZIP_SCORES_PATH

# Neighbours are found by buffering each gap polygon slightly and taking
# intersections, rather than a strict `touches` predicate: after coverage
# simplification the shared edges are no longer bit-identical, so exact
# topological touching is unreliable. 50m is wide enough to catch true
# neighbours across that drift, tight enough not to jump a channel.
NEIGHBOR_TOLERANCE_M = 50


def main():
    geo = gpd.read_parquet(ZCTA_GEOMETRIES_PATH).to_crs(EQUAL_AREA_CRS)
    scores = pd.read_parquet(ZIP_SCORES_PATH)
    scores["zcta5"] = scores["zcta5"].astype(str)

    score_cols = [c for c in scores.columns if c.endswith("_score") or c.endswith("_raw")]
    if not score_cols:
        raise RuntimeError("No score columns found -- run the category modules first.")

    # Any polygon in the geometry file with no score row at all also needs
    # filling, so start from the full polygon set.
    scores = geo[["zcta5"]].merge(scores, on="zcta5", how="left")

    needs_fill = scores[score_cols].isna().any(axis=1)
    n_gap = int(scores.loc[needs_fill, "zcta5"].str.startswith(NO_ZIP_PREFIX).sum())
    print(
        f"{len(scores)} polygons; {needs_fill.sum()} have >=1 missing score "
        f"({n_gap} no-ZIP, {int(needs_fill.sum()) - n_gap} regular ZCTAs)"
    )
    if not needs_fill.any():
        print("Nothing to fill.")
        return

    gaps = geo[geo["zcta5"].isin(scores.loc[needs_fill, "zcta5"])].reset_index(drop=True)
    # Donors are polygons with a complete set of scores.
    complete = scores[~needs_fill]
    real = geo.merge(complete[["zcta5", *score_cols]], on="zcta5", how="inner")

    probe = gaps.copy()
    probe["geometry"] = probe.geometry.buffer(NEIGHBOR_TOLERANCE_M)
    pairs = gpd.sjoin(
        probe[["zcta5", "geometry"]],
        real[["zcta5", "geometry"]].rename(columns={"zcta5": "neighbor"}),
        how="left",
        predicate="intersects",
    )

    # Weight each neighbour by how much boundary it shares with the gap:
    # the area of overlap between the buffered gap and that neighbour is a
    # cheap proxy for shared boundary length (buffer width is constant, so
    # overlap area ~ shared edge length x tolerance).
    probe_geom = probe.set_index("zcta5").geometry  # already buffered once
    real_geom = real.set_index("zcta5").geometry
    matched = pairs.dropna(subset=["neighbor"]).copy()

    # make_valid both operands: buffering a gap polygon can yield a ring
    # that self-touches, and GEOS aborts the whole intersection with
    # "side location conflict" rather than failing just that pair.
    left = shapely.make_valid(probe_geom.loc[matched["zcta5"]].to_numpy())
    right = shapely.make_valid(real_geom.loc[matched["neighbor"]].to_numpy())
    matched["weight"] = shapely.area(shapely.intersection(left, right))
    matched = matched[matched["weight"] > 0]

    real_scores = real.set_index("zcta5")[score_cols]
    vals = real_scores.loc[matched["neighbor"]].to_numpy()
    w = matched["weight"].to_numpy()[:, None]

    weighted = pd.DataFrame(vals * w, columns=score_cols)
    weighted["zcta5"] = matched["zcta5"].to_numpy()
    weighted["_w"] = w[:, 0]
    agg = weighted.groupby("zcta5").sum()
    interpolated = agg[score_cols].div(agg["_w"], axis=0)
    print(f"Interpolated {len(interpolated)} polygon(s) from shared-boundary neighbours")

    # Detached pieces with no touching neighbour: nearest scored polygon.
    orphans = gaps.loc[~gaps["zcta5"].isin(interpolated.index)]
    if len(orphans):
        nearest = gpd.sjoin_nearest(
            orphans[["zcta5", "geometry"]],
            real[["zcta5", "geometry"]].rename(columns={"zcta5": "neighbor"}),
            how="left",
        )
        nearest = nearest[~nearest.index.duplicated(keep="first")]
        fallback = real_scores.loc[nearest["neighbor"]].set_index(nearest["zcta5"].to_numpy())
        fallback.index.name = "zcta5"
        interpolated = pd.concat([interpolated, fallback])
        print(f"Filled {len(orphans)} detached piece(s) from nearest ZCTA")

    # Fill only the missing cells: a polygon may already have good
    # computed values for 7 categories and be NaN for just one, and those
    # real values must win over the interpolated estimate.
    out = scores.set_index("zcta5")
    out[score_cols] = out[score_cols].fillna(interpolated.reindex(out.index))
    out = out.reset_index()

    still_missing = int(out[score_cols].isna().any(axis=1).sum())
    if still_missing:
        raise RuntimeError(
            f"{still_missing} polygon(s) still missing scores after interpolation "
            f"(e.g. {out.loc[out[score_cols].isna().any(axis=1), 'zcta5'].head(5).tolist()})"
        )

    out.to_parquet(ZIP_SCORES_PATH)
    print(f"zip_scores now covers all {len(out)} polygons with no missing scores")


if __name__ == "__main__":
    main()
