"""
Clip no-ZIP gap areas against open water, and drop the slivers that leaves
behind.

Gap areas are derived from the Census county land mask (see
fetch_zcta_geometries.py), not from the basemap's own coastline -- and the
basemap (OpenFreeMap/OpenMapTiles, OSM-derived) draws water from a
different, independently-generalised source. The two disagree often
enough to be visible: a gap polygon can render as land-colored fill
sitting on top of what the map clearly shows as open water.

This is a render-only fix. It runs on zcta_geometries_render.parquet,
*after* build_render_geometries.py, and never touches the analysis
geometry or any hazard score -- a gap area's score is computed from its
full land-mask-derived shape, which is the geometry actually relevant to
"how much of this land is exposed to X", not to how the shape happens to
get drawn. Real ZCTAs are left alone entirely; only NOZIP-* rows are
touched, and each keeps its original id even where clipping reshapes it
into a MultiPolygon -- it's still the same gap area, just trimmed for
display.

Run: pixi run python pipeline/clip_gap_water.py
  (after build_render_geometries.py; rerun layer_writer.py +
  verify_layers.py afterward to pick up the change)
"""
import geopandas as gpd
import pandas as pd

from config import (
    EQUAL_AREA_CRS,
    NO_ZIP_PREFIX,
    WATER_CLIP_SLIVER_AREA_M2,
    WEB_CRS,
    ZCTA_RENDER_GEOMETRIES_PATH,
)
from geometry_utils import sanitize
from sources.natural_earth_water import load_water_union


def main():
    gdf = gpd.read_parquet(ZCTA_RENDER_GEOMETRIES_PATH).to_crs(EQUAL_AREA_CRS)
    is_gap = gdf["zcta5"].str.startswith(NO_ZIP_PREFIX)
    gaps, rest = gdf[is_gap].copy(), gdf[~is_gap]
    print(f"{len(gaps):,} gap polygons to check against water (of {len(gdf):,} total)")

    print("Loading Natural Earth ocean + lakes...")
    water = load_water_union()
    # Reproject the water union into the same equal-area CRS everything
    # else here works in, once, rather than per-polygon.
    water = gpd.GeoSeries([water], crs=WEB_CRS).to_crs(EQUAL_AREA_CRS).iloc[0]

    before_area = gaps.geometry.area.sum()
    clipped = gaps.geometry.difference(water).apply(sanitize)

    touched = (
        gaps.geometry.area - clipped.apply(lambda g: g.area if g is not None else 0)
    ).abs() > 1
    print(f"{int(touched.sum()):,} gap polygon(s) actually overlapped water")

    gaps["geometry"] = clipped
    dropped_empty = gaps.geometry.isna() | gaps.geometry.is_empty
    print(f"  {int(dropped_empty.sum()):,} fully dissolved into water -- dropping")
    gaps = gaps[~dropped_empty]

    sliver = gaps.geometry.area < WATER_CLIP_SLIVER_AREA_M2
    print(
        f"  {int(sliver.sum()):,} left under {WATER_CLIP_SLIVER_AREA_M2:,.0f} m^2 "
        "after clipping -- dropping as slivers"
    )
    gaps = gaps[~sliver]

    after_area = gaps.geometry.area.sum()
    print(
        f"Gap land area: {before_area / 1e6:,.1f} km^2 -> {after_area / 1e6:,.1f} km^2 "
        f"({(before_area - after_area) / 1e6:,.1f} km^2 removed as water/slivers)"
    )

    out = gpd.GeoDataFrame(
        pd.concat([rest, gaps], ignore_index=True), crs=EQUAL_AREA_CRS
    )
    out = out.to_crs(WEB_CRS)
    out.to_parquet(ZCTA_RENDER_GEOMETRIES_PATH)
    print(f"Wrote {len(out):,} polygons to {ZCTA_RENDER_GEOMETRIES_PATH}")


if __name__ == "__main__":
    main()
