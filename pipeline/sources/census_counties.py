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
# 2021 vintage, kept only for Connecticut -- see load_counties_legacy_ct().
COUNTIES_2021_URL = "https://www2.census.gov/geo/tiger/GENZ2021/shp/cb_2021_us_county_500k.zip"


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


@lru_cache(maxsize=1)
def load_counties_legacy_ct() -> gpd.GeoDataFrame:
    """Same as load_counties(), but with Connecticut's nine 2022+ Planning
    Regions swapped back for its eight legacy counties.

    Connecticut abolished county government as a statistical geography in
    2022; the 2023 file uses Planning Region GEOIDs (09110, 09120, ...)
    while any dataset covering earlier years still keys on legacy county
    FIPS (09001-09015). Joining the two silently matches nothing, which
    drops the entire state without raising -- exactly what happened to Air
    Quality (whose source covers 2015-2021) before this existed.

    Only use this for datasets keyed on pre-2022 county FIPS. Anything
    current (e.g. the Drought Monitor API) should use load_counties().
    """
    import pandas as pd

    zip_path = RAW_DIR / "cb_2021_us_county_500k.zip"
    extract_dir = RAW_DIR / "cb_2021_us_county_500k"

    if not zip_path.exists():
        RAW_DIR.mkdir(parents=True, exist_ok=True)
        print(f"Downloading {COUNTIES_2021_URL} ...")
        resp = requests.get(COUNTIES_2021_URL, timeout=120)
        resp.raise_for_status()
        zip_path.write_bytes(resp.content)

    if not extract_dir.exists():
        with zipfile.ZipFile(zip_path) as zf:
            zf.extractall(extract_dir)

    shp = next(extract_dir.glob("*.shp"))
    ct = gpd.read_file(shp)[["GEOID", "STATEFP", "NAME", "geometry"]]
    ct = ct[ct["STATEFP"] == "09"]
    if ct.crs is None or ct.crs.to_string() != WEB_CRS:
        ct = ct.to_crs(WEB_CRS)

    current = load_counties()
    combined = pd.concat([current[current["STATEFP"] != "09"], ct], ignore_index=True)
    return gpd.GeoDataFrame(combined, crs=WEB_CRS).reset_index(drop=True)
