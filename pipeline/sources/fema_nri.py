"""
FEMA National Risk Index (NRI) -- per-census-tract hazard risk metrics,
built by FEMA from modeled hazard frequency, building/population exposure,
and historical loss data. Queried live from NRI's ArcGIS FeatureServer
(same "query a live FEMA ArcGIS REST service" shape as
sources/fema_nfhl.py, just attribute-only -- no geometry, no per-county
bbox tiling, since this is one flat table keyed by tract FIPS rather than
a polygon layer that needs spatial scoping).

FEMA's own bulk CSV download (NRI_Table_CensusTracts) exists too, but its
current URL couldn't be pinned down: hazards.fema.gov's NRI download
pages now redirect into a consolidated fema.gov page (apparently
reorganized recently), and guessing at a URL risked silently pulling
nothing or a stale link. The FeatureServer is confirmed live.

Field chosen: HRCN_ALRB (Hurricane - Expected Annual Loss Rate -
Building), not HRCN_EALR (a categorical rating string like "Relatively
Low", despite its name -- confirmed by inspecting the live field list
and sample values, not assumed from the field alias) and not the
blended HRCN_RISKS score (which multiplies loss by a Social
Vulnerability / Community Resilience adjustment -- a different kind of
measure than every other hazard-exposure layer in this project). ALRB is
loss-per-dollar-of-exposure, so it isn't just a proxy for property
values in wealthy coastal areas the way a raw dollar loss field (EALB/
EALT) would be.
"""
import json
from pathlib import Path

import pandas as pd
import requests

from config import RAW_DIR

QUERY_URL = (
    "https://services.arcgis.com/XG15cJAlne2vxtgt/arcgis/rest/services/"
    "National_Risk_Index_Census_Tracts/FeatureServer/0/query"
)
PAGE_SIZE = 2000
CACHE_PATH = RAW_DIR / "nri_hurricane_alrb.json"


def _fetch_all_pages() -> list:
    features = []
    offset = 0
    while True:
        params = {
            "where": "1=1",
            "outFields": "TRACTFIPS,HRCN_ALRB",
            "returnGeometry": "false",
            "f": "json",
            "resultRecordCount": PAGE_SIZE,
            "resultOffset": offset,
        }
        resp = requests.get(QUERY_URL, params=params, timeout=120)
        resp.raise_for_status()
        page = resp.json().get("features", [])
        features.extend(page)
        if len(page) < PAGE_SIZE:
            break
        offset += PAGE_SIZE
    return features


def load_hurricane_alrb() -> pd.Series:
    """Hurricane Expected Annual Loss Rate - Building, indexed by census
    tract GEOID (TRACTFIPS, matching census_tracts.load_tracts()'s
    GEOID column). NaN entries (tracts with no building exposure to rate,
    e.g. unpopulated) are dropped -- area_weighted_average() already
    handles ZCTAs with no matched tract value by leaving them NaN for
    fill_nozip_scores to interpolate."""
    if CACHE_PATH.exists():
        features = json.loads(CACHE_PATH.read_text())
    else:
        print("Querying FEMA NRI Census Tracts FeatureServer for HRCN_ALRB...")
        features = _fetch_all_pages()
        RAW_DIR.mkdir(parents=True, exist_ok=True)
        CACHE_PATH.write_text(json.dumps(features))
        print(f"{len(features)} tracts fetched")

    rows = [f["attributes"] for f in features]
    df = pd.DataFrame(rows).rename(columns={"TRACTFIPS": "GEOID"})
    df = df.dropna(subset=["HRCN_ALRB"])
    return df.set_index("GEOID")["HRCN_ALRB"]
