"""
Verify every rendered layer is complete and cheap enough to load.

Three checks:

1. CONUS land coverage -- does the polygon set actually blanket CONUS
   land, or are there holes? Measured once against the Census county land
   mask (the same reference the gap-fill uses), because all layers are
   drawn from one shared geometry file, so their geometric coverage is
   identical by construction. Any hole would appear in all nine layers.
2. Per-layer integrity -- every layer must have one feature per polygon,
   no empty geometries, and a real score on every feature. A feature with
   a null score renders at the bottom of the colour ramp, which looks
   exactly like a hole.
3. Render cost -- file size and vertex count per layer, the two things
   that decide how long a layer switch takes in the browser.

Run: pixi run python pipeline/verify_layers.py
"""
import json

import geopandas as gpd

from config import (
    EQUAL_AREA_CRS,
    LAYERS_DIR,
    NO_ZIP_PREFIX,
    ZCTA_RENDER_GEOMETRIES_PATH,
)
from geometry_utils import sanitize_frame
from sources.census_counties import load_counties

# Coverage tolerance. The ZCTA layer and the county cartographic layer are
# generalised at different scales, so their coastlines never agree exactly
# and a slim ribbon of disagreement is unavoidable. Judge that by the size
# of the largest single piece, not the total: real coastline noise is
# thousands of slivers of ~1 km^2 each, whereas one missing ZCTA shows up
# as a single large blob. A 517 km^2 hole (two dropped Georgia ZCTAs) once
# passed a 5,000 km^2 total-area check precisely because the total was
# dominated by legitimate noise.
MAX_UNCOVERED_PIECE_KM2 = 25

# Coordinate snapping (meters) for the big union operations -- see
# check_land_coverage().
GRID_SIZE_M = 0.01


def check_land_coverage() -> bool:
    print("== CONUS land coverage ==")
    geo = gpd.read_parquet(ZCTA_RENDER_GEOMETRIES_PATH).to_crs(EQUAL_AREA_CRS)
    geo = sanitize_frame(geo, label="  ")
    land = load_counties().to_crs(EQUAL_AREA_CRS).union_all(grid_size=GRID_SIZE_M)

    # grid_size snaps coordinates before the union. Unioning ~47k polygons
    # whose shared edges agree only to floating-point precision otherwise
    # raises "side location conflict" -- 1cm is far below any tolerance
    # that matters here and makes the operation deterministic.
    covered = geo.union_all(grid_size=GRID_SIZE_M)
    uncovered = land.difference(covered)
    uncovered_km2 = uncovered.area / 1e6
    land_km2 = land.area / 1e6
    pct = 100 * uncovered_km2 / land_km2

    pieces = gpd.GeoDataFrame(geometry=[uncovered], crs=EQUAL_AREA_CRS).explode(
        index_parts=False
    )
    pieces["km2"] = pieces.geometry.area / 1e6
    pieces = pieces.sort_values("km2", ascending=False)
    largest = float(pieces["km2"].iloc[0]) if len(pieces) else 0.0

    print(f"  CONUS land:      {land_km2:>12,.0f} km^2")
    print(f"  Uncovered:       {uncovered_km2:>12,.0f} km^2  ({pct:.3f}%) in {len(pieces):,} pieces")
    print(f"  Largest hole:    {largest:>12,.1f} km^2  (limit {MAX_UNCOVERED_PIECE_KM2})")

    ok = largest <= MAX_UNCOVERED_PIECE_KM2
    if not ok:
        big = pieces[pieces["km2"] > MAX_UNCOVERED_PIECE_KM2].to_crs("EPSG:4326")
        print(f"  FAIL: {len(big)} hole(s) over the limit. Centroids (lon, lat):")
        for row in big.head(5).itertuples():
            c = row.geometry.centroid
            print(f"    {c.x:.3f}, {c.y:.3f}  ({row.km2:,.1f} km^2)")
    else:
        print("  PASS (remaining slivers are coastline-generalisation noise)")
    return ok


def check_layers(expected_features: int) -> bool:
    print("\n== Per-layer integrity and render cost ==")
    print(f"  {'layer':<20} {'features':>9} {'vertices':>11} {'MB':>7}  status")
    all_ok = True
    for path in sorted(LAYERS_DIR.glob("*.geojson")):
        with open(path) as f:
            data = json.load(f)
        feats = data["features"]

        problems = []
        if len(feats) != expected_features:
            problems.append(f"{len(feats)} features != {expected_features} polygons")

        empty = sum(1 for ft in feats if not ft.get("geometry") or not ft["geometry"]["coordinates"])
        if empty:
            problems.append(f"{empty} empty geometries")

        null_scores = sum(1 for ft in feats if ft["properties"].get("score") is None)
        if null_scores:
            problems.append(f"{null_scores} null scores")

        verts = sum(_count_coords(ft["geometry"]["coordinates"]) for ft in feats if ft.get("geometry"))
        mb = path.stat().st_size / 1e6
        status = "OK" if not problems else "FAIL: " + "; ".join(problems)
        all_ok &= not problems
        print(f"  {path.stem:<20} {len(feats):>9,} {verts:>11,} {mb:>7.1f}  {status}")
    return all_ok


def _count_coords(coords) -> int:
    if not coords:
        return 0
    if isinstance(coords[0], (int, float)):
        return 1
    return sum(_count_coords(c) for c in coords)


def main():
    geo = gpd.read_parquet(ZCTA_RENDER_GEOMETRIES_PATH)
    n_gap = int(geo["zcta5"].str.startswith(NO_ZIP_PREFIX).sum())
    print(f"{len(geo):,} polygons ({len(geo) - n_gap:,} ZCTAs + {n_gap:,} no-ZIP gap areas)\n")

    coverage_ok = check_land_coverage()
    layers_ok = check_layers(len(geo))

    print()
    if coverage_ok and layers_ok:
        print("All checks passed.")
    else:
        raise SystemExit("Verification FAILED -- see above.")


if __name__ == "__main__":
    main()
