"""Read-only access to pipeline output. The API never computes scores --
it only reads what pipeline/ already wrote.

Cached in memory keyed by the file's mtime (not a bare @lru_cache): the dev
server runs `--reload`, which only restarts on *code* changes, so a plain
process-lifetime cache would keep serving data from whenever it was first
read even after the pipeline rewrites the parquet file underneath it.

Deliberately no geopandas import anywhere in this module. The only thing
the API ever needs out of the geometry parquet is (a) a handful of plain
attribute columns and (b) one polygon's coordinates as GeoJSON on demand
-- both doable with plain pandas/pyarrow + shapely, which is a far
lighter, more serverless-friendly dependency footprint than pulling in
geopandas' full GDAL/GEOS/PROJ stack just to read a file column-wise.
"""
from pathlib import Path

import pandas as pd
import shapely

APP_DIR = Path(__file__).resolve().parent
BACKEND_DIR = APP_DIR.parent
ROOT_DIR = BACKEND_DIR.parent
DATA_DIR = ROOT_DIR / "data"

ZIP_SCORES_PATH = DATA_DIR / "zip_scores.parquet"
# Render geometry, not the full-detail analysis geometry: the API only
# serves geometry for display (the searched-ZCTA highlight outline), and
# using the same polygons the layers are drawn from keeps the highlight
# aligned with the rendered fill instead of tracing a slightly different
# edge.
ZCTA_GEOMETRIES_PATH = DATA_DIR / "zcta_geometries_render.parquet"
ZIP_TO_ZCTA_PATH = DATA_DIR / "zip_to_zcta.parquet"

# Id prefix the pipeline gives to land with no ZIP code. Duplicated from
# pipeline/config.py rather than imported: the backend deliberately has no
# dependency on the pipeline package, and only ever reads its output.
NO_ZIP_PREFIX = "NOZIP-"

_cache: dict = {}


def _load_if_stale(path: Path, key: str, loader):
    if not path.exists():
        raise FileNotFoundError(f"{path} not found -- run the pipeline first")
    mtime = path.stat().st_mtime
    cached = _cache.get(key)
    if cached is not None and cached[0] == mtime:
        return cached[1]
    value = loader()
    _cache[key] = (mtime, value)
    return value


def load_zcta_attrs() -> pd.DataFrame:
    """zcta5/state/county/population only -- no geometry column at all, so
    this never needs to touch shapely/geopandas. Used by the top-zones
    endpoint, which only ever displays these plain attributes."""

    def _load():
        df = pd.read_parquet(ZCTA_GEOMETRIES_PATH, columns=["zcta5", "state", "county", "population"])
        df["zcta5"] = df["zcta5"].astype(str).str.zfill(5)
        return df

    return _load_if_stale(ZCTA_GEOMETRIES_PATH, "zcta_attrs", _load)


def _load_zcta_geometries_raw() -> pd.DataFrame:
    """Full table including the geometry column, cached like everything
    else here -- the geometry column stays as raw WKB bytes until a
    specific row is actually requested, so caching it costs no more than
    caching the file itself."""

    def _load():
        df = pd.read_parquet(ZCTA_GEOMETRIES_PATH)
        df["zcta5"] = df["zcta5"].astype(str).str.zfill(5)
        return df

    return _load_if_stale(ZCTA_GEOMETRIES_PATH, "zcta_geometries_raw", _load)


def load_zcta_geometry_feature(zcta5: str) -> dict | None:
    """Single ZCTA as a GeoJSON Feature dict, or None if not found. Only
    the requested row's WKB gets decoded with shapely.from_wkb() -- see
    module docstring for why this avoids geopandas entirely."""
    zcta5 = str(zcta5).zfill(5)
    df = _load_zcta_geometries_raw()
    row = df.loc[df["zcta5"] == zcta5]
    if row.empty:
        return None
    row = row.iloc[0]
    geom = shapely.from_wkb(row["geometry"])
    properties = row.drop("geometry").to_dict()
    return {"type": "Feature", "geometry": shapely.geometry.mapping(geom), "properties": properties}


def load_zip_to_zcta() -> dict:
    """ZIP -> {zcta5, zip_type, join_type} as a plain dict, since the only
    access pattern is single-key lookup on every search request."""

    def _load():
        df = pd.read_parquet(ZIP_TO_ZCTA_PATH)
        df["zip5"] = df["zip5"].astype(str).str.zfill(5)
        # NaN -> None so callers can distinguish "no ZCTA exists for this
        # ZIP" from "ZIP not found" without a float-NaN check.
        df["zcta5"] = df["zcta5"].where(df["zcta5"].notna(), None)
        return {
            r.zip5: {"zcta5": r.zcta5, "zip_type": r.zip_type, "join_type": r.join_type}
            for r in df.itertuples()
        }

    return _load_if_stale(ZIP_TO_ZCTA_PATH, "zip_to_zcta", _load)


def load_zip_scores() -> pd.DataFrame:
    def _load():
        df = pd.read_parquet(ZIP_SCORES_PATH)
        df["zcta5"] = df["zcta5"].astype(str).str.zfill(5)
        return df

    return _load_if_stale(ZIP_SCORES_PATH, "zip_scores", _load)
