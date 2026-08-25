"""
Split no-ZIP gap areas so each sits in one state and is zip-code-scale,
and record which state every polygon belongs to.

Two problems with gap areas as first produced:

* TIGER assigns no ZCTA to large tracts of public land -- national
  forest, BLM range, desert -- and because those tracts touch, they merge
  into single enormous polygons. The worst reached 239,912 km^2, larger
  than Wyoming. Scores are computed per polygon, so a blob that size gets
  one flood number and one wildfire number averaged across half the West,
  which describes nowhere inside it.
* They freely straddle state lines, so a gap area can't be attributed to
  a state -- which the "highest-risk zones per layer" table needs.

Three passes, in this order:

1. State split. Every gap area is clipped to state boundaries, so no
   piece spans two states. This has to come first: splitting by size and
   then by state would re-fragment the results.
2. Proximity. Oversized pieces are partitioned among the real ZCTAs
   around them by Voronoi tessellation on their centroids, so a piece
   means "the unassigned land nearest zip X" rather than an arbitrary
   rectangle.
3. Bisection. Voronoi guarantees nothing -- wilderness far from any zip
   can still come out oversized -- so anything still over the limit is
   cut along its longer axis until it fits.

Real ZCTAs are left alone: they are genuine zip areas, and a few really
do straddle state lines. They're assigned the state holding most of their
area.

Run: pixi run python pipeline/subdivide_large_gaps.py
  (after fetch_zcta_geometries.py, before build_render_geometries.py)
"""
import geopandas as gpd
import numpy as np
import pandas as pd
from shapely import make_valid, voronoi_polygons
from shapely.geometry import MultiPoint, box

from config import (
    EQUAL_AREA_CRS,
    MAX_GAP_AREA_MEDIAN_MULTIPLE,
    MIN_GAP_AREA_M2,
    NO_ZIP_PREFIX,
    WEB_CRS,
    ZCTA_GEOMETRIES_PATH,
)
from geometry_utils import sanitize_frame
from sources.census_counties import load_counties
from sources.nws_zones import FIPS_TO_POSTAL

# How far out to look for real ZCTAs to seed the tessellation: wide enough
# to find neighbours around a broad blob, tight enough to keep the seed
# count (and the Voronoi cost) sane.
SEED_SEARCH_BUFFER_M = 50_000


def _states() -> gpd.GeoDataFrame:
    """State polygons, dissolved from the county file already on disk
    rather than downloading a separate boundary set."""
    counties = load_counties().to_crs(EQUAL_AREA_CRS)
    states = counties.dissolve(by="STATEFP", as_index=False)[["STATEFP", "geometry"]]
    states["geometry"] = states["geometry"].apply(make_valid)
    states["state"] = states["STATEFP"].astype(int).map(FIPS_TO_POSTAL)
    return states.dropna(subset=["state"])[["state", "geometry"]]


def _bisect(geom, max_area: float, depth: int = 0):
    """Cut along the longer axis until every piece fits."""
    if geom.area <= max_area or depth > 12:
        return [geom]
    minx, miny, maxx, maxy = geom.bounds
    if (maxx - minx) >= (maxy - miny):
        mid = (minx + maxx) / 2
        halves = [box(minx, miny, mid, maxy), box(mid, miny, maxx, maxy)]
    else:
        mid = (miny + maxy) / 2
        halves = [box(minx, miny, maxx, mid), box(minx, mid, maxx, maxy)]

    out = []
    for half in halves:
        part = geom.intersection(half)
        if part.is_empty:
            continue
        for p in getattr(part, "geoms", [part]):
            if p.geom_type in ("Polygon", "MultiPolygon") and p.area > 0:
                out.extend(_bisect(p, max_area, depth + 1))
    return out or [geom]


def _split_by_proximity(geom, seeds: np.ndarray, max_area: float):
    if len(seeds) < 2:
        return _bisect(geom, max_area)

    cells = voronoi_polygons(MultiPoint(seeds.tolist()), extend_to=box(*geom.bounds))
    pieces = []
    for cell in getattr(cells, "geoms", [cells]):
        part = geom.intersection(cell)
        if part.is_empty:
            continue
        for p in getattr(part, "geoms", [part]):
            if p.geom_type in ("Polygon", "MultiPolygon") and p.area > MIN_GAP_AREA_M2:
                pieces.extend(_bisect(p, max_area))
    return pieces or _bisect(geom, max_area)


def main():
    gdf = gpd.read_parquet(ZCTA_GEOMETRIES_PATH).to_crs(EQUAL_AREA_CRS)
    is_gap = gdf["zcta5"].str.startswith(NO_ZIP_PREFIX)
    real = gdf[~is_gap].copy()
    gaps = gdf[is_gap]

    states = _states()
    median_area = real.geometry.area.median()
    max_area = MAX_GAP_AREA_MEDIAN_MULTIPLE * median_area
    print(
        f"Median real ZCTA {median_area / 1e6:.1f} km^2; "
        f"gap-area limit {max_area / 1e6:.1f} km^2"
    )

    # Real ZCTAs: keep whole, label with whichever state holds most of them.
    print(f"Attributing {len(real):,} real ZCTAs to states...")
    ov = gpd.overlay(
        real[["zcta5", "geometry"]], states, how="intersection", keep_geom_type=True
    )
    ov["a"] = ov.geometry.area
    dominant = ov.sort_values("a").groupby("zcta5")["state"].last()
    real["state"] = real["zcta5"].map(dominant)

    # Gap areas: clip to state lines first, then split anything oversized.
    print(f"Splitting {len(gaps):,} gap areas at state lines...")
    inside = gpd.overlay(
        gaps[["zcta5", "geometry"]], states, how="intersection", keep_geom_type=True
    )

    # Whatever falls outside every state polygon has to be reattached, not
    # dropped. The state outlines come from the county file, which is
    # water-clipped along the coast, while the gap areas deliberately
    # include tidal marsh reclaimed by the coastal-closing step -- so a
    # plain intersection silently deletes exactly the marsh that was added
    # to close the Charleston/Savannah holes in the first place. Measured
    # at 13,797 km^2 lost before this was added.
    # make_valid on both operands: GEOS raises "side location conflict" on
    # a difference where either side has a self-touching ring, which the
    # dissolved state outlines do have along a few coastlines.
    state_union = make_valid(states.geometry.union_all())
    residual = gaps.geometry.apply(make_valid).difference(state_union)
    residual = gpd.GeoDataFrame(geometry=residual[~residual.is_empty], crs=EQUAL_AREA_CRS)
    residual = residual.explode(index_parts=False)
    residual = residual[residual.geometry.area >= MIN_GAP_AREA_M2].reset_index(drop=True)
    if len(residual):
        # Nearest state, so these still satisfy one-polygon-one-state.
        residual = residual.sjoin_nearest(states, how="left")
        residual = residual[~residual.index.duplicated(keep="first")]
        print(
            f"  reattached {len(residual):,} offshore/marsh piece(s) "
            f"({residual.geometry.area.sum() / 1e6:,.0f} km^2) to their nearest state"
        )

    gap_by_state = gpd.GeoDataFrame(
        pd.concat([inside[["state", "geometry"]], residual[["state", "geometry"]]], ignore_index=True),
        crs=EQUAL_AREA_CRS,
    )
    gap_by_state = gap_by_state[gap_by_state.geometry.area >= MIN_GAP_AREA_M2].reset_index(drop=True)
    print(f"  -> {len(gap_by_state):,} single-state pieces")

    oversized = gap_by_state[gap_by_state.geometry.area > max_area]
    keep = gap_by_state[gap_by_state.geometry.area <= max_area]
    print(
        f"{len(oversized):,} still oversized, holding "
        f"{oversized.geometry.area.sum() / 1e6:,.0f} km^2"
    )

    real_centroids = real.geometry.centroid
    sindex = real_centroids.sindex

    rows = []
    for i, r in enumerate(oversized.itertuples(), start=1):
        idx = list(sindex.query(r.geometry.buffer(SEED_SEARCH_BUFFER_M), predicate="intersects"))
        seeds = np.array([[p.x, p.y] for p in real_centroids.iloc[idx]])
        for piece in _split_by_proximity(r.geometry, seeds, max_area):
            rows.append({"state": r.state, "geometry": piece})
        if i % 25 == 0 or i == len(oversized):
            print(f"  [{i}/{len(oversized)}] -> {len(rows):,} pieces so far")

    split = gpd.GeoDataFrame(rows, crs=EQUAL_AREA_CRS) if rows else gpd.GeoDataFrame(
        {"state": [], "geometry": []}, crs=EQUAL_AREA_CRS
    )
    split = split[split.geometry.area >= MIN_GAP_AREA_M2]

    all_gaps = gpd.GeoDataFrame(
        pd.concat([keep[["state", "geometry"]], split], ignore_index=True),
        crs=EQUAL_AREA_CRS,
    )
    all_gaps["zcta5"] = [f"{NO_ZIP_PREFIX}{i:05d}" for i in range(1, len(all_gaps) + 1)]

    out = gpd.GeoDataFrame(
        pd.concat(
            [real[["zcta5", "state", "geometry"]], all_gaps[["zcta5", "state", "geometry"]]],
            ignore_index=True,
        ),
        crs=EQUAL_AREA_CRS,
    )

    # Clean before writing: the Voronoi/bisection intersections above can
    # produce malformed polygons that break every downstream consumer.
    out = sanitize_frame(out, label="  ")

    areas = all_gaps.geometry.area / 1e6
    print(
        f"Gap areas: {len(gaps):,} -> {len(all_gaps):,}  "
        f"(largest {areas.max():,.1f} km^2, was {gaps.geometry.area.max() / 1e6:,.0f})"
    )
    unlabelled = int(out["state"].isna().sum())
    if unlabelled:
        print(f"WARNING: {unlabelled} polygon(s) have no state label")

    out.to_crs(WEB_CRS).to_parquet(ZCTA_GEOMETRIES_PATH)
    print(f"Wrote {len(out):,} polygons to {ZCTA_GEOMETRIES_PATH}")


if __name__ == "__main__":
    main()
