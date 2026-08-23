"""
Restore any ZCTA that exists in the raw TIGER source but is missing from
the processed geometry.

Geometry processing can lose a polygon -- coverage simplification may
leave one self-intersecting, and an unguarded validity filter then drops
it. That leaves a hole in the map *and* makes the ZIP un-searchable in the
API, which is worse than it looks: it is silent. fetch_zcta_geometries.py
now repairs rather than discards, so this should find nothing on a fresh
build; it exists to fix an already-built dataset without a full rebuild.

Why surgical rather than re-running fetch_zcta_geometries: the NOZIP-#####
gap identifiers are assigned by row order, so a rebuild renumbers them and
orphans every gap polygon's already-computed scores, downgrading ~4,800
polygons from directly-computed to interpolated. Patching in place keeps
all of that intact.

Restored polygons are clipped against the existing coverage so they can
only fill genuine holes, never overlap a neighbour. They have no scores
afterwards -- run fill_nozip_scores.py next to interpolate them from
their neighbours (or re-run the category modules for exact values).

Run: pixi run python pipeline/repair_missing_zctas.py
"""
import geopandas as gpd
import pandas as pd
import pyogrio
from shapely import make_valid

from config import (
    CONUS_BBOX,
    EQUAL_AREA_CRS,
    RAW_DIR,
    WEB_CRS,
    ZCTA_GEOMETRIES_PATH,
)

SHAPEFILE = RAW_DIR / "tl_2023_us_zcta520" / "tl_2023_us_zcta520.shp"


def main():
    gdf = gpd.read_parquet(ZCTA_GEOMETRIES_PATH)
    have = set(gdf["zcta5"])

    # Read codes only (no geometry) -- fast scan of ~33k rows.
    codes = pyogrio.read_dataframe(SHAPEFILE, columns=["ZCTA5CE20"], read_geometry=False)
    candidates = sorted(set(codes["ZCTA5CE20"]) - have)
    if not candidates:
        print("No missing ZCTAs.")
        return

    # Pull geometry only for the candidates, then keep the CONUS ones --
    # everything outside CONUS is out of scope and legitimately absent.
    quoted = ",".join(f"'{c}'" for c in candidates)
    missing = pyogrio.read_dataframe(SHAPEFILE, where=f"ZCTA5CE20 IN ({quoted})")
    missing = missing.rename(columns={"ZCTA5CE20": "zcta5"})[["zcta5", "geometry"]]
    if missing.crs is None or missing.crs.to_string() != WEB_CRS:
        missing = missing.to_crs(WEB_CRS)

    minx, miny, maxx, maxy = CONUS_BBOX
    missing = missing.cx[minx:maxx, miny:maxy]
    if missing.empty:
        print(f"{len(candidates)} missing ZCTA(s), all outside CONUS -- nothing to restore.")
        return

    print(f"Restoring {len(missing)} CONUS ZCTA(s): {missing['zcta5'].tolist()}")

    missing = missing.to_crs(EQUAL_AREA_CRS)
    missing["geometry"] = missing["geometry"].apply(make_valid)

    # Clip to the existing hole so a restored polygon can only add
    # coverage, never overlap a neighbour that already claims that ground.
    existing = gdf.to_crs(EQUAL_AREA_CRS).union_all()
    missing["geometry"] = missing.geometry.difference(existing)
    missing = missing[~missing.geometry.is_empty & missing.geometry.notna()]

    for row in missing.itertuples():
        print(f"  {row.zcta5}: {row.geometry.area / 1e6:,.1f} km^2 restored")

    out = gpd.GeoDataFrame(
        pd.concat([gdf, missing.to_crs(WEB_CRS)], ignore_index=True), crs=WEB_CRS
    )
    out.to_parquet(ZCTA_GEOMETRIES_PATH)
    print(f"Wrote {len(out)} polygons to {ZCTA_GEOMETRIES_PATH} (was {len(gdf)})")
    print("Next: fill_nozip_scores.py -> composite.py -> layer_writer.py")


if __name__ == "__main__":
    main()
