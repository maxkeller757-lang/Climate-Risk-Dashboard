"""
Natural Earth 10m ocean + lake polygons -- used only to clip no-ZIP gap
areas away from open water for display, not for anything analytical.

This is a deliberate approximation, in the same spirit as the coastal
gap-fill step's 5km closing buffer: the basemap's own water rendering
comes from OSM-derived vector tiles (OpenFreeMap/OpenMapTiles), not from
Natural Earth, so the two coastlines won't align to the pixel. Natural
Earth at 10m is coarse enough to be fast and easy to work with, and fine
enough that the mismatch is invisible at the zoom levels this map
actually renders at -- the same tradeoff already accepted for the county
land mask used elsewhere in this pipeline.
"""
import zipfile
from functools import lru_cache

import geopandas as gpd
import requests
from shapely.ops import unary_union

from config import CONUS_BBOX, RAW_DIR, WEB_CRS

OCEAN_URL = "https://naciscdn.org/naturalearth/10m/physical/ne_10m_ocean.zip"
LAKES_URL = "https://naciscdn.org/naturalearth/10m/physical/ne_10m_lakes.zip"


def _download_shapefile(url: str, name: str) -> gpd.GeoDataFrame:
    zip_path = RAW_DIR / f"{name}.zip"
    extract_dir = RAW_DIR / name

    if not zip_path.exists():
        RAW_DIR.mkdir(parents=True, exist_ok=True)
        print(f"Downloading {url} ...")
        resp = requests.get(url, timeout=120)
        resp.raise_for_status()
        zip_path.write_bytes(resp.content)

    if not extract_dir.exists():
        with zipfile.ZipFile(zip_path) as zf:
            zf.extractall(extract_dir)

    shp = next(extract_dir.glob("*.shp"))
    gdf = gpd.read_file(shp)
    if gdf.crs is None or gdf.crs.to_string() != WEB_CRS:
        gdf = gdf.to_crs(WEB_CRS)
    return gdf


@lru_cache(maxsize=1)
def load_water_union():
    """Single dissolved (Multi)Polygon of ocean + major lakes, clipped to
    the CONUS bbox with some margin. Returned as one unified shapely
    geometry (not a GeoDataFrame) since every caller just wants to
    difference() against it."""
    minx, miny, maxx, maxy = CONUS_BBOX
    # A little padding so ocean polygons that extend past the strict bbox
    # (e.g. the Gulf, the Pacific) still clip cleanly at the coastline
    # rather than getting cut off mid-ocean right at the bbox edge.
    pad = 2.0
    ocean = _download_shapefile(OCEAN_URL, "ne_10m_ocean").cx[
        minx - pad : maxx + pad, miny - pad : maxy + pad
    ]
    lakes = _download_shapefile(LAKES_URL, "ne_10m_lakes").cx[
        minx - pad : maxx + pad, miny - pad : maxy + pad
    ]
    return unary_union(list(ocean.geometry) + list(lakes.geometry))
