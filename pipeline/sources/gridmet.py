"""
gridMET (University of Idaho / climatologylab.org), CONUS ~4km daily
gridded meteorology. Used for both Extreme Heat sub-components (raw max
temp threshold, and the temp+humidity blend for heat index) -- the project
brief describes those as coming from two different products (NCEI
nClimGrid-Daily for the temp threshold, gridMET for heat index), but using
gridMET alone for both avoids pulling two redundant 10-year CONUS daily
grids for what both ultimately measure (daily max temp), and keeps the
two sub-components internally consistent with each other.

Source: https://www.climatologylab.org/gridmet.html
"""
from pathlib import Path

import numpy as np
import requests

from config import RAW_DIR

BASE_URL = "http://www.northwestknowledge.net/metdata/data"


def download_year(variable: str, year: int) -> Path:
    """variable: 'tmmx' (daily max temp, Kelvin) or 'rmin' (daily min
    relative humidity, %)."""
    path = RAW_DIR / f"{variable}_{year}.nc"
    if not path.exists():
        RAW_DIR.mkdir(parents=True, exist_ok=True)
        url = f"{BASE_URL}/{variable}_{year}.nc"
        print(f"Downloading {url} ...")
        with requests.get(url, stream=True, timeout=600) as r:
            r.raise_for_status()
            with open(path, "wb") as f:
                for chunk in r.iter_content(chunk_size=1 << 20):
                    f.write(chunk)
    return path


def kelvin_to_fahrenheit(k: np.ndarray) -> np.ndarray:
    return (k - 273.15) * 9.0 / 5.0 + 32.0
