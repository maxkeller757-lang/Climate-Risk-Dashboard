"""
Split no-ZIP gap areas so each sits in one state and is zip-code-scale,
and record which state, county, and population every real ZCTA has.

Two problems with gap areas as first produced:

* TIGER assigns no ZCTA to large tracts of public land -- national
  forest, BLM range, desert -- and because those tracts touch, they merge
  into single enormous polygons. The worst reached 239,912 km^2, larger
  than Wyoming. Scores are computed per polygon, so a blob that size gets
  one flood number and one wildfire number averaged across half the West,
  which describes nowhere inside it.
* They freely straddle state lines, so a gap area can't be attributed to
  a state -- which the "highest-risk zones per layer" table needs.

Real ZCTAs also get a county name and an apportioned population here, for
that same table: county so a result reads as somewhere recognisable
rather than a bare zip code, and population so genuine score ties
(several ZCTAs pinned at the same raw ceiling -- 21 of them at 100%
floodplain, for instance) break toward the place where the hazard
affects more people, rather than an arbitrary row order. Population
apportionment mirrors severe_convective.py's reporting-bias correction:
county population (Census Population Estimates) spread across ZCTAs by
intersection-area share of each county.

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
import hashlib

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
from sources.census_population import load_county_population
from sources.nws_zones import FIPS_TO_POSTAL
from spatial import area_apportioned_sum

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


def _stable_gap_ids(geometries) -> list:
    """Deterministic NOZIP-* ids, derived from each polygon's own geometry
    rather than its row position in this run.

    Sequential numbering (NOZIP-00001, NOZIP-00002, ...) looked stable but
    wasn't: rerunning this script rebuilds the whole gap-area set from
    scratch, and nothing guarantees polygon #4534 lands in the same row on
    two different runs -- GEOS intersection/Voronoi output order, sort
    tie-breaking, and the marsh-reattachment sjoin_nearest step can all
    reorder it. Every category script upserts its score into
    zip_scores.parquet keyed on this string id via an OUTER JOIN, so a
    reordering doesn't leave the new polygon unscored (which would at
    least get caught by fill_nozip_scores.py) -- it silently reattaches an
    OLD score computed for a completely different, unrelated polygon.
    Confirmed happening in production: interior-Oregon gap areas were
    showing hurricane scores near 100, and gap areas in south TX/FL/LA
    were showing seismic scores far too high, in both cases because they'd
    inherited another gap polygon's score from an earlier subdivide run.

    Deriving the id from geometry instead fixes this at the root: the same
    physical polygon gets the same id every run, so its score stays
    validly attached across reruns, and only a polygon that's genuinely
    new or changed shape gets a new id -- which correctly leaves it
    unscored until the category scripts run again, rather than wrongly
    inheriting someone else's number.
    """
    ids = []
    seen: dict = {}
    for geom in geometries:
        c = geom.centroid
        # Round to the nearest meter -- far finer than needed to
        # distinguish two real gap polygons, coarse enough to absorb the
        # sub-meter floating-point jitter repeated GEOS operations can
        # introduce run to run for what is "the same" polygon.
        key = f"{round(c.x)}_{round(c.y)}_{round(geom.area)}"
        digest = hashlib.sha1(key.encode()).hexdigest()[:10]
        # A genuine collision (two distinct polygons hashing the same) is
        # astronomically unlikely at this precision, but guard it anyway
        # rather than silently merging two different pieces of land onto
        # one id.
        n = seen.get(digest, 0)
        seen[digest] = n + 1
        ids.append(f"{NO_ZIP_PREFIX}{digest}" + (f"-{n}" if n else ""))
    return ids


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

    # Same dominant-area rule, against counties this time -- gives a
    # human-recognisable place name to go with the state abbreviation.
    print(f"Attributing {len(real):,} real ZCTAs to counties...")
    counties = load_counties().to_crs(EQUAL_AREA_CRS)
    counties["geometry"] = counties["geometry"].apply(make_valid)
    cov = gpd.overlay(
        real[["zcta5", "geometry"]],
        counties[["NAME", "geometry"]],
        how="intersection",
        keep_geom_type=True,
    )
    cov["a"] = cov.geometry.area
    dominant_county = cov.sort_values("a").groupby("zcta5")["NAME"].last()
    real["county"] = real["zcta5"].map(dominant_county)

    # Population, areally apportioned from county totals -- same method
    # severe_convective.py uses for its reporting-bias correction. Used
    # here only to break genuine score ties toward the more populous
    # place; not otherwise part of any hazard score.
    print("Apportioning county population onto ZCTAs...")
    population = load_county_population()
    pop_by_zcta = area_apportioned_sum(real, counties, "GEOID", population)
    real["population"] = real["zcta5"].map(
        pop_by_zcta.set_index("zcta5")["value"]
    ).fillna(0)

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
    all_gaps["zcta5"] = _stable_gap_ids(all_gaps.geometry)
    # Gap areas have no county/population: they're excluded from the
    # "highest risk" table entirely, and a dominant-county overlay over
    # ~14k of them would cost real time for a value nothing ever reads.
    all_gaps["county"] = None
    all_gaps["population"] = 0.0

    out = gpd.GeoDataFrame(
        pd.concat(
            [
                real[["zcta5", "state", "county", "population", "geometry"]],
                all_gaps[["zcta5", "state", "county", "population", "geometry"]],
            ],
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
