"""
NCEI Storm Events Database ingestion, shared by the Severe Convective
(Tornado/Hail/Thunderstorm Wind) and Winter Weather (Winter Storm/Ice
Storm/Heavy Snow/Blizzard) categories -- both read the same bulk "details"
CSVs, just filtered to different EVENT_TYPE values.

Source: https://www.ncei.noaa.gov/pub/data/swdi/stormevents/csvfiles/
"""
import re
from functools import lru_cache
from pathlib import Path

import geopandas as gpd
import pandas as pd
import requests

from config import END_YEAR, RAW_DIR, START_YEAR, WEB_CRS

INDEX_URL = "https://www.ncei.noaa.gov/pub/data/swdi/stormevents/csvfiles/"

DETAIL_COLUMNS = [
    "EVENT_ID",
    "EVENT_TYPE",
    "BEGIN_DATE_TIME",
    "BEGIN_LAT",
    "BEGIN_LON",
    "MAGNITUDE",
    "MAGNITUDE_TYPE",
    "TOR_F_SCALE",
    "DEATHS_DIRECT",
    "INJURIES_DIRECT",
    "STATE",
]


@lru_cache(maxsize=1)
def _list_index() -> str:
    resp = requests.get(INDEX_URL, timeout=60)
    resp.raise_for_status()
    return resp.text


def _details_filename_for_year(year: int) -> str:
    """NCEI filenames carry a file-creation-date suffix
    (StormEvents_details-ftp_v1.0_d{YEAR}_c{CREATED}.csv.gz) that changes as
    NOAA reprocesses older years, so list the index page instead of
    hardcoding names. If a year has been reprocessed more than once, take
    the most recently created file."""
    html = _list_index()
    pattern = rf"StormEvents_details-ftp_v1\.0_d{year}_c\d+\.csv\.gz"
    matches = sorted(set(re.findall(pattern, html)))
    if not matches:
        raise FileNotFoundError(f"No StormEvents details file found for {year} at {INDEX_URL}")
    return matches[-1]


def download_details_csv(year: int) -> Path:
    return _download(_details_filename_for_year(year))


def _locations_filename_for_year(year: int) -> str:
    html = _list_index()
    pattern = rf"StormEvents_locations-ftp_v1\.0_d{year}_c\d+\.csv\.gz"
    matches = sorted(set(re.findall(pattern, html)))
    if not matches:
        raise FileNotFoundError(f"No StormEvents locations file found for {year} at {INDEX_URL}")
    return matches[-1]


def download_locations_csv(year: int) -> Path:
    return _download(_locations_filename_for_year(year))


def _download(filename: str) -> Path:
    RAW_DIR.mkdir(parents=True, exist_ok=True)
    dest = RAW_DIR / filename
    if dest.exists():
        return dest
    url = INDEX_URL + filename
    print(f"Downloading {url} ...")
    resp = requests.get(url, timeout=300)
    resp.raise_for_status()
    dest.write_bytes(resp.content)
    print(f"Saved {dest} ({dest.stat().st_size / 1e6:.1f} MB)")
    return dest


def _fill_missing_coords_from_locations(df: pd.DataFrame, year: int) -> pd.DataFrame:
    """Some event types (Winter Storm/Ice Storm/Heavy Snow/Blizzard among
    them) are reported by NWS zone in the details file and carry no
    BEGIN_LAT/BEGIN_LON at all. The companion "locations" bulk file has
    point coordinates keyed by EVENT_ID (potentially several points per
    event, e.g. a path's start/end); average them into one representative
    point per event and use that to fill the gap."""
    missing = df["BEGIN_LAT"].isna() | df["BEGIN_LON"].isna()
    if not missing.any():
        return df

    locs = pd.read_csv(download_locations_csv(year), compression="gzip", low_memory=False)
    locs = locs.dropna(subset=["LATITUDE", "LONGITUDE"])
    agg = locs.groupby("EVENT_ID")[["LATITUDE", "LONGITUDE"]].mean()

    df = df.copy()
    df.loc[missing, "BEGIN_LAT"] = df.loc[missing, "EVENT_ID"].map(agg["LATITUDE"])
    df.loc[missing, "BEGIN_LON"] = df.loc[missing, "EVENT_ID"].map(agg["LONGITUDE"])
    return df


def load_events(
    event_types: list[str],
    start_year: int = START_YEAR,
    end_year: int = END_YEAR,
) -> gpd.GeoDataFrame:
    """Load NCEI Storm Events of the given EVENT_TYPE values across
    [start_year, end_year] as point geometries at the event begin location.
    Events with no usable begin lat/lon are dropped."""
    frames = []
    for year in range(start_year, end_year + 1):
        path = download_details_csv(year)
        df = pd.read_csv(path, compression="gzip", low_memory=False)
        df = df[df["EVENT_TYPE"].isin(event_types)]
        keep = [c for c in DETAIL_COLUMNS if c in df.columns]
        df = df[keep]
        df = _fill_missing_coords_from_locations(df, year)
        frames.append(df)

    all_events = pd.concat(frames, ignore_index=True)
    all_events = all_events.dropna(subset=["BEGIN_LAT", "BEGIN_LON"])

    return gpd.GeoDataFrame(
        all_events,
        geometry=gpd.points_from_xy(all_events["BEGIN_LON"], all_events["BEGIN_LAT"]),
        crs=WEB_CRS,
    )


ZONE_EVENT_COLUMNS = DETAIL_COLUMNS + ["CZ_TYPE", "CZ_FIPS", "STATE_FIPS"]


def load_zone_events(
    event_types: list[str],
    start_year: int = START_YEAR,
    end_year: int = END_YEAR,
) -> pd.DataFrame:
    """Load NCEI Storm Events reported by NWS zone (CZ_TYPE == 'Z') rather
    than point location. Winter Storm/Ice Storm/Heavy Snow/Blizzard are
    recorded this way exclusively -- no lat/lon exists anywhere in the bulk
    data for them (see nws_zones.py). Returns event rows keyed by
    STATE_ZONE (matches the NWS public zones shapefile's STATE_ZONE field),
    not by geometry."""
    from .nws_zones import FIPS_TO_POSTAL

    frames = []
    for year in range(start_year, end_year + 1):
        path = download_details_csv(year)
        df = pd.read_csv(path, compression="gzip", low_memory=False)
        df = df[(df["EVENT_TYPE"].isin(event_types)) & (df["CZ_TYPE"] == "Z")]
        keep = [c for c in ZONE_EVENT_COLUMNS if c in df.columns]
        frames.append(df[keep])

    events = pd.concat(frames, ignore_index=True)
    events = events.dropna(subset=["CZ_FIPS", "STATE_FIPS"])
    events["postal"] = events["STATE_FIPS"].astype(int).map(FIPS_TO_POSTAL)
    events = events.dropna(subset=["postal"])  # drops non-CONUS states/territories
    events["STATE_ZONE"] = (
        events["postal"] + events["CZ_FIPS"].astype(int).astype(str).str.zfill(3)
    )
    return events


def severity_weight(row: pd.Series) -> float:
    """Per-event severity multiplier. Documented here rather than left
    implicit: EF/magnitude-scaled for event types that carry a usable
    magnitude field, otherwise a flat count-weighted fallback.

    NOTE: this is a v1 heuristic, not a validated meteorological index --
    reasonable starting weights, worth revisiting against domain literature
    before treating the severity_score as authoritative."""
    event_type = row.get("EVENT_TYPE")

    if event_type == "Tornado":
        scale = str(row.get("TOR_F_SCALE") or "")
        digits = "".join(ch for ch in scale if ch.isdigit())
        ef = int(digits) if digits else 0
        return 1.0 + ef  # EF0 -> 1, EF5 -> 6

    if event_type == "Hail":
        mag = row.get("MAGNITUDE")
        return 1.0 + (float(mag) if pd.notna(mag) else 0.0)  # inches diameter

    if event_type == "Thunderstorm Wind":
        mag = row.get("MAGNITUDE")
        return 1.0 + (float(mag) / 50.0 if pd.notna(mag) else 0.0)  # knots, scaled down

    # Winter Storm / Ice Storm / Heavy Snow / Blizzard: NCEI's MAGNITUDE
    # field is largely unpopulated for these types, so weight on reported
    # direct deaths/injuries as a severity proxy, falling back to a flat
    # count (weight 1) when neither is reported.
    deaths = row.get("DEATHS_DIRECT") or 0
    injuries = row.get("INJURIES_DIRECT") or 0
    return 1.0 + 2.0 * float(deaths) + 0.5 * float(injuries)
