"""
Build data/zcta_geometries_render.parquet: a coarser copy of the analysis
geometry, used only for drawing the map.

Scoring needs accurate polygons (areas, overlaps, zonal stats), but the
browser does not -- at CONUS zoom a ZCTA is a few pixels wide, so the
analysis geometry's detail is invisible and just costs download and parse
time. Simplifying once here, rather than per layer, keeps all 9 layers
consistent and does the work a single time.

Two properties this must preserve:
  * Coverage topology -- simplify_coverage() keeps shared edges identical
    between neighbours, so no slivers or overlaps appear between ZCTAs.
  * Every polygon -- aggressive simplification can collapse a small
    polygon to nothing, which punches a real hole in the map (this bit us
    before via shapely.set_precision). Anything that collapses keeps its
    original geometry instead.

Run: pixi run python pipeline/build_render_geometries.py
"""
import geopandas as gpd
from shapely import get_parts, make_valid
from shapely.ops import unary_union

from config import (
    EQUAL_AREA_CRS,
    MIN_GAP_AREA_M2,
    RENDER_SIMPLIFY_TOLERANCE_M,
    WEB_CRS,
    ZCTA_GEOMETRIES_PATH,
    ZCTA_RENDER_GEOMETRIES_PATH,
)


def main():
    gdf = gpd.read_parquet(ZCTA_GEOMETRIES_PATH).to_crs(EQUAL_AREA_CRS)
    before = _vertex_count(gdf)

    # Drop specks that cannot survive the writer's coordinate rounding --
    # they would come out as empty geometry and read as holes. At a few
    # square meters they are invisible at any zoom this map supports.
    too_small = gdf.geometry.area < MIN_GAP_AREA_M2
    if too_small.any():
        total_m2 = gdf.loc[too_small].geometry.area.sum()
        print(f"Dropping {too_small.sum()} sub-{MIN_GAP_AREA_M2}m^2 polygon(s), {total_m2:,.0f} m^2 total")
        gdf = gdf[~too_small].reset_index(drop=True)

    # Normalise before simplifying. Subdividing the gap areas (Voronoi
    # cells and axis bisections, both intersections) can leave a polygon
    # carrying a degenerate ring -- a ring of a single point. Those have
    # real area so the size filter above keeps them, but simplify_coverage
    # rejects the whole coverage with "point array must contain 0 or >1
    # elements" as soon as it meets one.
    before_area = gdf.geometry.area.sum()
    gdf["geometry"] = gdf.geometry.apply(_sanitize)
    unusable = gdf.geometry.isna() | gdf.geometry.is_empty
    if unusable.any():
        print(f"Dropping {int(unusable.sum())} unrepairable geometry/geometries")
        gdf = gdf[~unusable].reset_index(drop=True)
    lost = before_area - gdf.geometry.area.sum()
    if lost > 0:
        print(f"  area lost to cleaning: {lost / 1e6:,.3f} km^2")

    print(f"Simplifying {len(gdf)} polygons for render (tolerance={RENDER_SIMPLIFY_TOLERANCE_M}m)...")
    simplified = gdf.geometry.simplify_coverage(
        RENDER_SIMPLIFY_TOLERANCE_M, simplify_boundary=True
    )

    collapsed = simplified.is_empty | simplified.isna() | ~simplified.is_valid
    if collapsed.any():
        print(f"  {collapsed.sum()} polygon(s) collapsed or went invalid -- keeping original geometry")
        simplified = simplified.where(~collapsed, gdf.geometry)

    gdf["geometry"] = simplified

    # Re-apply the size filter *after* simplifying, not just before.
    # Simplification shrinks polygons, so a sliver can clear the threshold
    # going in and come out with almost nothing left -- 16 gap slivers
    # totalling 3,015 m^2 (several of them 0 m^2) survived the earlier
    # filter, then wrote out as empty geometry and tripped the layer
    # verification.
    shrunk = gdf.geometry.area < MIN_GAP_AREA_M2
    if shrunk.any():
        print(
            f"Dropping {int(shrunk.sum())} polygon(s) that simplification shrank below "
            f"{MIN_GAP_AREA_M2} m^2 ({gdf.loc[shrunk].geometry.area.sum():,.0f} m^2 total)"
        )
        gdf = gdf[~shrunk].reset_index(drop=True)

    gdf = gdf.to_crs(WEB_CRS)

    after = _vertex_count(gdf)
    print(f"Vertices: {before:,} -> {after:,} ({100 * after / before:.0f}%)")

    gdf.to_parquet(ZCTA_RENDER_GEOMETRIES_PATH)
    print(f"Wrote {len(gdf)} polygons to {ZCTA_RENDER_GEOMETRIES_PATH}")


def _polygonal_only(geom):
    """Strip non-polygonal debris (stray lines/points a repair can leave)."""
    if geom is None or geom.is_empty or geom.geom_type in ("Polygon", "MultiPolygon"):
        return geom
    parts = [g for g in get_parts(geom) if g.geom_type in ("Polygon", "MultiPolygon")]
    return unary_union(parts) if parts else None


def _sanitize(geom):
    """Coerce one geometry into a clean valid polygon, or None.

    simplify_coverage refuses the entire coverage if any single member is
    malformed, and the gap-area subdivision (Voronoi cells and axis
    bisections, both intersections) can emit polygons that are typed
    correctly but carry a degenerate ring. Those survive a geom_type check
    and can even defeat make_valid, which raises "Overlay input is
    mixed-dimension" on some of them -- so each repair is attempted
    defensively and anything still unusable is dropped rather than allowed
    to abort the run.
    """
    if geom is None or geom.is_empty:
        return None
    geom = _polygonal_only(geom)
    if geom is None or geom.is_empty:
        return None
    if geom.is_valid:
        return geom
    for repair in (make_valid, lambda g: g.buffer(0)):
        try:
            fixed = _polygonal_only(repair(geom))
        except Exception:
            continue
        if fixed is not None and not fixed.is_empty and fixed.is_valid:
            return fixed
    return None


def _vertex_count(gdf: gpd.GeoDataFrame) -> int:
    return int(gdf.geometry.count_coordinates().sum())


if __name__ == "__main__":
    main()
