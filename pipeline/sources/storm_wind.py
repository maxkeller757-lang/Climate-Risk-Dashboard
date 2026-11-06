"""
STORM tropical-cyclone maximum wind speed (m/s) return-period rasters:
10,000 years of synthetic cyclone tracks (Bloemendaal et al.), published as
global 10km GeoTIFFs, one per return period, CC0. The "constant" files are
the present-day climate baseline.

A pure meteorological wind hazard -- unlike FEMA NRI's loss rate, it does
not fold building age/value into the number. Pixels with no cyclone
exposure are a literal 0.0 (inland CONUS), which is the correct raw value,
not a nodata sentinel.

Source: https://zenodo.org/records/7438145
"""
from pathlib import Path

import requests

from config import RAW_DIR

RETURN_PERIOD_YEARS = 50
FILENAME = f"STORM_FIXED_RETURN_PERIODS_constant_{RETURN_PERIOD_YEARS}_YR_RP.tif"
URL = f"https://zenodo.org/api/records/7438145/files/{FILENAME}/content"


def download_wind_speed_raster() -> Path:
    path = RAW_DIR / FILENAME
    if not path.exists():
        RAW_DIR.mkdir(parents=True, exist_ok=True)
        print(f"Downloading {URL} ...")
        resp = requests.get(URL, timeout=300)
        resp.raise_for_status()
        path.write_bytes(resp.content)
    return path
