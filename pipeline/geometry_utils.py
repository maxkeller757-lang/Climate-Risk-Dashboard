"""
Shared geometry cleaning.

Subdividing the no-ZIP gap areas relies on intersections -- Voronoi cells
and axis-aligned bisections -- and those can emit polygons that pass a
geom_type check while being internally malformed, typically carrying a
degenerate single-point ring. They are a small minority and have real
area, so nothing upstream filters them out, but downstream they are
poison: simplify_coverage rejects an entire coverage the moment it meets
one, and geopandas overlay raises "Overlay input is mixed-dimension" from
inside make_valid. That failure took out five category modules at once.

Repairing has to be attempted defensively, because make_valid itself is
one of the things that can raise on these inputs.
"""
import geopandas as gpd
from shapely import get_parts, make_valid
from shapely.ops import unary_union

POLYGONAL = ("Polygon", "MultiPolygon")


def polygonal_only(geom):
    """Strip non-polygonal debris (stray lines/points from a repair)."""
    if geom is None or geom.is_empty or geom.geom_type in POLYGONAL:
        return geom
    parts = [g for g in get_parts(geom) if g.geom_type in POLYGONAL]
    return unary_union(parts) if parts else None


def sanitize(geom):
    """Coerce one geometry to a clean valid polygon, or None if hopeless."""
    if geom is None or geom.is_empty:
        return None
    geom = polygonal_only(geom)
    if geom is None or geom.is_empty:
        return None
    if geom.is_valid:
        return geom
    for repair in (make_valid, lambda g: g.buffer(0)):
        try:
            fixed = polygonal_only(repair(geom))
        except Exception:
            continue
        if fixed is not None and not fixed.is_empty and fixed.is_valid:
            return fixed
    return None


def sanitize_frame(gdf: gpd.GeoDataFrame, label: str = "") -> gpd.GeoDataFrame:
    """Sanitize every geometry, dropping any that can't be repaired.

    Reports how much area was lost, because dropping a polygon punches a
    hole in CONUS coverage and that should never pass unnoticed.
    """
    before_area = gdf.geometry.area.sum()
    out = gdf.copy()
    out["geometry"] = out.geometry.apply(sanitize)

    unusable = out.geometry.isna() | out.geometry.is_empty
    if unusable.any():
        print(f"{label}Dropping {int(unusable.sum())} unrepairable geometry/geometries")
        out = out[~unusable].reset_index(drop=True)

    lost = before_area - out.geometry.area.sum()
    if abs(lost) > 1:
        print(f"{label}Area change from cleaning: {lost / 1e6:,.3f} km^2")
    return out
