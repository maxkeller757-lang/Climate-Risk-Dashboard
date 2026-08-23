"""
NOAA/NWS Public Forecast Zones -- the geometry NCEI Storm Events uses to
report zone-based event types (Winter Storm, Ice Storm, Heavy Snow,
Blizzard all carry CZ_TYPE == 'Z', with no point lat/lon anywhere in the
bulk data, unlike Tornado/Hail/Thunderstorm Wind).

Source: https://www.weather.gov/gis/PublicZones
"""
import zipfile
from functools import lru_cache

import geopandas as gpd
import requests

from config import RAW_DIR, WEB_CRS

# Dated filename per NOAA's publishing convention; check
# https://www.weather.gov/gis/PublicZones for the current one if this 404s.
ZONES_URL = "https://www.weather.gov/source/gis/Shapefiles/WSOM/z_18mr25.zip"

# NCEI STATE_FIPS (numeric) -> USPS postal abbreviation, needed to build the
# zone shapefile's STATE_ZONE join key (STATE postal + zero-padded ZONE).
# CONUS + DC only, matching this project's scope.
FIPS_TO_POSTAL = {
    1: "AL", 4: "AZ", 5: "AR", 6: "CA", 8: "CO", 9: "CT", 10: "DE", 11: "DC",
    12: "FL", 13: "GA", 16: "ID", 17: "IL", 18: "IN", 19: "IA", 20: "KS",
    21: "KY", 22: "LA", 23: "ME", 24: "MD", 25: "MA", 26: "MI", 27: "MN",
    28: "MS", 29: "MO", 30: "MT", 31: "NE", 32: "NV", 33: "NH", 34: "NJ",
    35: "NM", 36: "NY", 37: "NC", 38: "ND", 39: "OH", 40: "OK", 41: "OR",
    42: "PA", 44: "RI", 45: "SC", 46: "SD", 47: "TN", 48: "TX", 49: "UT",
    50: "VT", 51: "VA", 53: "WA", 54: "WV", 55: "WI", 56: "WY",
}


@lru_cache(maxsize=1)
def load_zones() -> gpd.GeoDataFrame:
    zip_path = RAW_DIR / "z_18mr25.zip"
    extract_dir = RAW_DIR / "nws_zones"

    if not zip_path.exists():
        RAW_DIR.mkdir(parents=True, exist_ok=True)
        print(f"Downloading {ZONES_URL} ...")
        resp = requests.get(ZONES_URL, timeout=120)
        resp.raise_for_status()
        zip_path.write_bytes(resp.content)

    if not extract_dir.exists():
        with zipfile.ZipFile(zip_path) as zf:
            zf.extractall(extract_dir)

    shp = next(extract_dir.glob("*.shp"))
    gdf = gpd.read_file(shp)[["STATE_ZONE", "STATE", "ZONE", "NAME", "geometry"]]
    if gdf.crs is None or gdf.crs.to_string() != WEB_CRS:
        gdf = gdf.to_crs(WEB_CRS)
    return gdf
