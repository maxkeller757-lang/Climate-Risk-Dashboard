"""
NOAA NHC HURDAT2 Atlantic hurricane best-track database. Fixed-format text:
a header line per storm ("AL092021,             IDA,     39,") followed by
that many 6-hourly track lines ("20210828, 1200,  , HU, 29.1N,  90.2W,
130, ...").

Source: https://www.nhc.noaa.gov/data/#hurdat
"""
import re
from pathlib import Path

import geopandas as gpd
import pandas as pd
import requests

from config import END_YEAR, RAW_DIR, START_YEAR, WEB_CRS

INDEX_URL = "https://www.nhc.noaa.gov/data/hurdat/"
HEADER_RE = re.compile(r"^(AL\d{6}),\s*([^,]*),\s*(\d+),\s*$")


def _hurdat2_filename() -> str:
    html = requests.get(INDEX_URL, timeout=60).text
    matches = sorted(set(re.findall(r"hurdat2-1851-\d{4}-\d{8}\.txt", html)))
    if not matches:
        raise FileNotFoundError(f"No HURDAT2 file found at {INDEX_URL}")
    return matches[-1]


def download_hurdat2() -> Path:
    RAW_DIR.mkdir(parents=True, exist_ok=True)
    filename = _hurdat2_filename()
    dest = RAW_DIR / filename
    if not dest.exists():
        url = INDEX_URL + filename
        print(f"Downloading {url} ...")
        resp = requests.get(url, timeout=120)
        resp.raise_for_status()
        dest.write_bytes(resp.content)
    return dest


def _parse_latlon(lat: str, lon: str) -> tuple:
    lat_val = float(lat[:-1]) * (1 if lat.endswith("N") else -1)
    lon_val = float(lon[:-1]) * (1 if lon.endswith("E") else -1)
    return lat_val, lon_val


def load_track_points(
    start_year: int = START_YEAR, end_year: int = END_YEAR
) -> gpd.GeoDataFrame:
    """6-hourly track points (lat, lon, max_wind in knots, year) for every
    storm with at least one observation in [start_year, end_year]."""
    path = download_hurdat2()
    rows = []
    with open(path) as f:
        lines = f.readlines()

    i = 0
    while i < len(lines):
        header = HEADER_RE.match(lines[i])
        if not header:
            i += 1
            continue
        storm_id, name, n_lines = header.group(1), header.group(2).strip(), int(header.group(3))
        for j in range(i + 1, i + 1 + n_lines):
            fields = [f.strip() for f in lines[j].split(",")]
            date = fields[0]
            year = int(date[:4])
            if start_year <= year <= end_year:
                lat, lon = _parse_latlon(fields[4], fields[5])
                max_wind = float(fields[6])
                if max_wind > 0:
                    rows.append(
                        {"storm_id": storm_id, "name": name, "year": year,
                         "max_wind": max_wind, "lat": lat, "lon": lon}
                    )
        i += 1 + n_lines

    df = pd.DataFrame(rows)
    return gpd.GeoDataFrame(
        df, geometry=gpd.points_from_xy(df["lon"], df["lat"]), crs=WEB_CRS
    )
