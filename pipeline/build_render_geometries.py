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

    print(f"Simplifying {len(gdf)} polygons for render (tolerance={RENDER_SIMPLIFY_TOLERANCE_M}m)...")
    simplified = gdf.geometry.simplify_coverage(
        RENDER_SIMPLIFY_TOLERANCE_M, simplify_boundary=True
    )

    collapsed = simplified.is_empty | simplified.isna() | ~simplified.is_valid
    if collapsed.any():
        print(f"  {collapsed.sum()} polygon(s) collapsed or went invalid -- keeping original geometry")
        simplified = simplified.where(~collapsed, gdf.geometry)

    gdf["geometry"] = simplified
    gdf = gdf.to_crs(WEB_CRS)

    after = _vertex_count(gdf)
    print(f"Vertices: {before:,} -> {after:,} ({100 * after / before:.0f}%)")

    gdf.to_parquet(ZCTA_RENDER_GEOMETRIES_PATH)
    print(f"Wrote {len(gdf)} polygons to {ZCTA_RENDER_GEOMETRIES_PATH}")


def _vertex_count(gdf: gpd.GeoDataFrame) -> int:
    return int(gdf.geometry.count_coordinates().sum())


if __name__ == "__main__":
    main()
