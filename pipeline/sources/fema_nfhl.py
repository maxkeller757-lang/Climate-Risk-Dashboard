"""
FEMA National Flood Hazard Layer (NFHL) -- Special Flood Hazard Area (SFHA,
i.e. Zone A/AE/V/VE) polygons.

FEMA doesn't publish a single national bulk download (data is per-state/
county through the Map Service Center portal); instead this queries the
live ArcGIS REST service directly. Each CONUS county's bounding box (from
sources/census_counties.py -- used purely as a tiling grid, not for its own
geometry) scopes one query, keeping each request's result under the
service's 2000-record page limit. Per-county results are cached to disk so
a rerun only re-fetches counties that are new or previously failed.
"""
import json

import geopandas as gpd
import pandas as pd
import requests

from config import RAW_DIR, WEB_CRS

QUERY_URL = "https://hazards.fema.gov/arcgis/rest/services/public/NFHL/MapServer/28/query"
PAGE_SIZE = 2000
# Degrees (~50m at mid-latitudes): generalizes geometry server-side to keep
# payloads small. ZCTA geometries are already simplified to a coarser
# tolerance (config.GEOJSON_SIMPLIFY_TOLERANCE), so this adds no meaningful
# error to the % area overlay.
GENERALIZE_TOLERANCE = 0.0005

CACHE_DIR = RAW_DIR / "nfhl_by_county"


def _fetch_county_features(bbox: tuple) -> list:
    minx, miny, maxx, maxy = bbox
    features = []
    offset = 0
    while True:
        params = {
            "where": "SFHA_TF='T'",
            "geometry": f"{minx},{miny},{maxx},{maxy}",
            "geometryType": "esriGeometryEnvelope",
            "inSR": 4269,
            "spatialRel": "esriSpatialRelIntersects",
            "outFields": "OBJECTID",
            "returnGeometry": "true",
            "f": "geojson",
            "resultRecordCount": PAGE_SIZE,
            "resultOffset": offset,
            "maxAllowableOffset": GENERALIZE_TOLERANCE,
        }
        resp = requests.get(QUERY_URL, params=params, timeout=120)
        resp.raise_for_status()
        page = resp.json().get("features", [])
        features.extend(page)
        if len(page) < PAGE_SIZE:
            break
        offset += PAGE_SIZE
    return features


def _query_county(bbox: tuple, geoid: str) -> gpd.GeoDataFrame:
    cache_path = CACHE_DIR / f"{geoid}.geojson"
    if cache_path.exists():
        return gpd.read_file(cache_path)

    features = _fetch_county_features(bbox)
    if not features:
        return gpd.GeoDataFrame({"OBJECTID": []}, geometry=[], crs=WEB_CRS)

    gdf = gpd.GeoDataFrame.from_features(features, crs=4269).to_crs(WEB_CRS)
    CACHE_DIR.mkdir(parents=True, exist_ok=True)
    gdf.to_file(cache_path, driver="GeoJSON")
    return gdf


def load_sfha_polygons(counties: gpd.GeoDataFrame) -> gpd.GeoDataFrame:
    """SFHA polygons for every CONUS county, deduplicated by OBJECTID
    (adjacent counties' bboxes overlap, so the same flood polygon can be
    returned by more than one query)."""
    frames = []
    total = len(counties)
    for i, row in enumerate(counties.itertuples(), start=1):
        bbox = row.geometry.bounds
        try:
            gdf = _query_county(bbox, row.GEOID)
        except requests.RequestException as exc:
            print(f"  [{i}/{total}] county {row.GEOID} FAILED: {exc}")
            continue
        if len(gdf):
            frames.append(gdf)
        if i % 200 == 0 or i == total:
            n_polys = sum(len(f) for f in frames)
            print(f"  [{i}/{total}] counties queried, {n_polys} SFHA polygons so far")

    all_polys = pd.concat(frames, ignore_index=True)
    all_polys = gpd.GeoDataFrame(all_polys, crs=WEB_CRS)
    return all_polys.drop_duplicates(subset="OBJECTID").reset_index(drop=True)
