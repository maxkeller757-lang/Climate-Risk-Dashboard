"""
Census cartographic boundary county polygons (2023, 1:500,000). Used as a
shared tiling/query unit -- not to compute anything about counties
themselves -- by both Flood (bbox-scoping FEMA NFHL REST queries) and
Drought (joining USDM's county-level statistics API to ZCTAs).
"""
import zipfile
from functools import lru_cache

import geopandas as gpd
import requests

from config import CONUS_BBOX, RAW_DIR, WEB_CRS

COUNTIES_URL = "https://www2.census.gov/geo/tiger/GENZ2023/shp/cb_2023_us_county_500k.zip"


@lru_cache(maxsize=1)
def load_counties() -> gpd.GeoDataFrame:
    zip_path = RAW_DIR / "cb_2023_us_county_500k.zip"
    extract_dir = RAW_DIR / "cb_2023_us_county_500k"

    if not zip_path.exists():
        RAW_DIR.mkdir(parents=True, exist_ok=True)
        print(f"Downloading {COUNTIES_URL} ...")
        resp = requests.get(COUNTIES_URL, timeout=120)
        resp.raise_for_status()
        zip_path.write_bytes(resp.content)

    if not extract_dir.exists():
        with zipfile.ZipFile(zip_path) as zf:
            zf.extractall(extract_dir)

    shp = next(extract_dir.glob("*.shp"))
    gdf = gpd.read_file(shp)[["GEOID", "STATEFP", "NAME", "geometry"]]
    if gdf.crs is None or gdf.crs.to_string() != WEB_CRS:
        gdf = gdf.to_crs(WEB_CRS)

    minx, miny, maxx, maxy = CONUS_BBOX
    gdf = gdf.cx[minx:maxx, miny:maxy]
    return gdf.reset_index(drop=True)
