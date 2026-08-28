"""
Patch a small, hand-reviewed list of individual bad vertices in
zcta_geometries.parquet -- digitization artifacts in the raw TIGER source
that survive simplify_coverage() because they're too large a deviation
for coverage-preserving simplification to touch.

Only analysis geometry is patched here, not zcta_geometries_render.parquet:
build_render_geometries.py (which runs after this in refresh_all.py)
derives render geometry from analysis geometry, so it inherits the fix
automatically on a full rebuild.

Each entry names the exact (lon, lat) vertex to drop, not a heuristic
("the southernmost point" etc.) -- a future TIGER vintage could reshape a
ZCTA enough that a heuristic starts deleting a real vertex instead. If a
registered vertex is no longer found, this raises rather than silently
no-op'ing, so a source update that already fixed (or moved) the defect
gets noticed instead of masked.

A zcta5 can list more than one vertex -- applied in list order, each one
re-validated before the next. Order matters: for 55605, both vertices are
part of the same southward excursion, but removing the second (more
northerly) one first, or removing both at once, both produce a
self-intersection (it cuts across nearby fine coastline detail from a
different direction). Removing the more southerly one first, then the
other from the result, is valid. A third vertex in that same excursion
(the most northerly of the three, closest to the real coastline) can't be
removed this way at all without a self-intersection -- it survives as a
small residual dip, undoing that would need re-drawing with a new point,
which the "only existing vertices" constraint here rules out.

Run: pixi run python pipeline/fix_zcta_geometry_defects.py
  (right after fetch_zcta_geometries.py, before anything reads the file)
"""
import geopandas as gpd
from shapely.geometry import Polygon

from config import ZCTA_GEOMETRIES_PATH

# zcta5 -> [((lon, lat), reason), ...], applied in order.
DEFECTS = {
    "55605": [
        (
            (-89.64103115922651, 47.77511530326033),
            "TIGER digitization spike: a lone vertex ~28km south of the rest "
            "of this ZCTA's Lake Superior shoreline, dragging a triangular "
            "wedge of open water into the polygon. Confirmed unique to this "
            "ZCTA (not a shared boundary vertex with any neighbour) before "
            "removal.",
        ),
        (
            (-89.62517814071424, 47.79955436741371),
            "Second vertex of the same excursion, ~9km south of the "
            "surrounding coastline -- became the new southernmost point "
            "after the first removal above and was still pulling in open "
            "water. Also confirmed unique to this ZCTA.",
        ),
    ],
}


def main():
    gdf = gpd.read_parquet(ZCTA_GEOMETRIES_PATH)
    fixed = 0
    for zcta5, defects in DEFECTS.items():
        matches = gdf.index[gdf["zcta5"] == zcta5]
        if len(matches) == 0:
            raise RuntimeError(f"fix_zcta_geometry_defects: {zcta5} not found in geometry file")
        idx = matches[0]
        for bad_coord, reason in defects:
            geom = gdf.loc[idx, "geometry"]
            coords = list(geom.exterior.coords)
            try:
                bad_i = coords.index(bad_coord)
            except ValueError:
                raise RuntimeError(
                    f"fix_zcta_geometry_defects: registered vertex {bad_coord} for "
                    f"{zcta5} not found -- geometry changed upstream, re-verify this fix "
                    f"still applies ({reason})"
                )
            new_poly = Polygon(coords[:bad_i] + coords[bad_i + 1 :])
            if not new_poly.is_valid:
                raise RuntimeError(
                    f"fix_zcta_geometry_defects: removing vertex {bad_coord} from "
                    f"{zcta5} produced an invalid polygon"
                )
            gdf.loc[idx, "geometry"] = new_poly
            fixed += 1
            print(f"{zcta5}: removed vertex {bad_coord} ({reason.splitlines()[0]})")

    gdf.to_parquet(ZCTA_GEOMETRIES_PATH)
    print(f"Fixed {fixed} geometry defect(s)")


if __name__ == "__main__":
    main()
