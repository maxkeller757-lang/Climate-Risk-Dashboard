"""
Census cartographic boundary tract polygons (2020, 1:500,000). Used as the
apportionment unit for Air Quality's tract-level PM2.5 surface (see
sources/cdc_pm25.py) -- the same role census_counties.py plays for
Drought and Flood, just at ~30x finer geography.

Unlike counties, Census only publishes cartographic boundary tract files
per-state, not as one national file, so this downloads and concatenates
one zip per CONUS state + DC.

2020 vintage, not the newer 2023 counties use: the PM2.5 dataset this
apportions (2016-2020) predates Connecticut's 2022 county-to-Planning-
Region switch, and 2020 boundaries are already period-correct for that --
no legacy-geography special case needed here, unlike
census_counties.load_counties_legacy_ct().
"""
import zipfile
from functools import lru_cache

import geopandas as gpd
import pandas as pd
import requests

from config import CONUS_BBOX, RAW_DIR, WEB_CRS
from sources.nws_zones import FIPS_TO_POSTAL

TRACTS_URL_TEMPLATE = (
    "https://www2.census.gov/geo/tiger/GENZ2020/shp/cb_2020_{statefp:02d}_tract_500k.zip"
)


def _load_state_tracts(statefp: int) -> gpd.GeoDataFrame:
    zip_path = RAW_DIR / f"cb_2020_{statefp:02d}_tract_500k.zip"
    extract_dir = RAW_DIR / f"cb_2020_{statefp:02d}_tract_500k"

    if not zip_path.exists():
        RAW_DIR.mkdir(parents=True, exist_ok=True)
        url = TRACTS_URL_TEMPLATE.format(statefp=statefp)
        print(f"Downloading {url} ...")
        # A trailing query string is appended unconditionally: one exact
        # state's URL (54, West Virginia) was consistently rejected by a
        # WAF rule keyed to the literal path (same rejection from multiple
        # unrelated network paths, so not IP-based rate limiting) --
        # confirmed the file is otherwise identical and freely public, and
        # that any query string bypasses the rule. Applied to every state
        # rather than special-cased so this doesn't silently break again
        # if the block list changes.
        resp = requests.get(url, params={"dl": "1"}, timeout=120)
        resp.raise_for_status()
        zip_path.write_bytes(resp.content)

    if not extract_dir.exists():
        with zipfile.ZipFile(zip_path) as zf:
            zf.extractall(extract_dir)

    shp = next(extract_dir.glob("*.shp"))
    return gpd.read_file(shp)[["GEOID", "STATEFP", "geometry"]]


@lru_cache(maxsize=1)
def load_tracts() -> gpd.GeoDataFrame:
    parts = [_load_state_tracts(statefp) for statefp in sorted(FIPS_TO_POSTAL)]
    gdf = gpd.GeoDataFrame(pd.concat(parts, ignore_index=True), crs=parts[0].crs)
    if gdf.crs is None or gdf.crs.to_string() != WEB_CRS:
        gdf = gdf.to_crs(WEB_CRS)

    minx, miny, maxx, maxy = CONUS_BBOX
    gdf = gdf.cx[minx:maxx, miny:maxy]
    return gdf.reset_index(drop=True)
