"""
U.S. Drought Monitor county-level statistics, via UNL's public REST API
(https://usdmdataservices.unl.edu). No bulk national download of a
ready-aggregated "avg % time in drought" exists, so this queries per-county
(the API's finest addressable unit) for the full 2015-2024 window in one
call each, and averages the weekly D0 ("abnormally dry or worse", i.e. any
drought) percentage locally. Results are cached per-county so a rerun after
a partial failure only re-fetches what's missing.
"""
import io

import geopandas as gpd
import pandas as pd
import requests

from config import END_YEAR, RAW_DIR, START_YEAR

API_URL = (
    "https://usdmdataservices.unl.edu/api/CountyStatistics/"
    "GetDroughtSeverityStatisticsByAreaPercent"
)
CACHE_DIR = RAW_DIR / "usdm_by_county"


def _fetch_county(fips: str) -> pd.DataFrame:
    cache_path = CACHE_DIR / f"{fips}.csv"
    if cache_path.exists():
        return pd.read_csv(cache_path)

    params = {
        "aoi": fips,
        "startdate": f"1/1/{START_YEAR}",
        "enddate": f"12/31/{END_YEAR}",
        "statisticsType": "1",
    }
    resp = requests.get(API_URL, params=params, timeout=60)
    resp.raise_for_status()
    df = pd.read_csv(io.StringIO(resp.text)) if resp.text.strip() else pd.DataFrame()

    CACHE_DIR.mkdir(parents=True, exist_ok=True)
    df.to_csv(cache_path, index=False)
    return df


def load_avg_drought_pct(counties: gpd.GeoDataFrame) -> pd.Series:
    """Average % of each county's area in D0-or-worse drought over the
    START_YEAR-END_YEAR window, indexed by county GEOID (5-digit FIPS)."""
    values = {}
    total = len(counties)
    for i, row in enumerate(counties.itertuples(), start=1):
        try:
            df = _fetch_county(row.GEOID)
        except requests.RequestException as exc:
            print(f"  [{i}/{total}] county {row.GEOID} FAILED: {exc}")
            continue
        if len(df) and "D0" in df.columns:
            values[row.GEOID] = df["D0"].mean()
        if i % 200 == 0 or i == total:
            print(f"  [{i}/{total}] counties queried")

    return pd.Series(values, name="avg_drought_pct")
