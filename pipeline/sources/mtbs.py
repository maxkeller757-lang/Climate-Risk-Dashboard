"""
MTBS (Monitoring Trends in Burn Severity) national historical burn
perimeters, filtered to 2015-2024 -- the "historical supplement" component
of Wildfire (the primary component is USFS Wildfire Hazard Potential, a
point-in-time model; see wildfire.py).

Read directly out of the downloaded zip via GDAL's /vsizip/ virtual
filesystem with an attribute pushdown filter -- the shapefile is 616MB, but
we only need ~10k of its ~30k+ all-time records, so there's no need to
extract or load the rest.

Source: https://www.mtbs.gov/direct-download
"""
from pathlib import Path

import geopandas as gpd
import requests

from config import END_YEAR, RAW_DIR, START_YEAR, WEB_CRS

PERIMETER_URL = (
    "https://edcintl.cr.usgs.gov/downloads/sciweb1/shared/MTBS_Fire/data/"
    "composite_data/burned_area_extent_shapefile/mtbs_perimeter_data.zip"
)


def _download() -> Path:
    zip_path = RAW_DIR / "mtbs_perimeter_data.zip"
    if not zip_path.exists():
        RAW_DIR.mkdir(parents=True, exist_ok=True)
        print(f"Downloading {PERIMETER_URL} ...")
        resp = requests.get(PERIMETER_URL, timeout=900)
        resp.raise_for_status()
        zip_path.write_bytes(resp.content)
    return zip_path


def load_burn_perimeters(
    start_year: int = START_YEAR, end_year: int = END_YEAR
) -> gpd.GeoDataFrame:
    zip_path = _download()
    vsizip_path = f"/vsizip/{zip_path.as_posix()}/mtbs_perims_DD.shp"
    gdf = gpd.read_file(
        vsizip_path,
        where=f"ig_date >= '{start_year}-01-01' AND ig_date <= '{end_year}-12-31'",
        columns=["event_id", "incid_name", "ig_date", "burnbndac"],
    )
    return gdf.to_crs(WEB_CRS)
