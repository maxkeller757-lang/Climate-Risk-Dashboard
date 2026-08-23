"""Read-only access to pipeline output. The API never computes scores --
it only reads what pipeline/ already wrote.

Cached in memory keyed by the file's mtime (not a bare @lru_cache): the dev
server runs `--reload`, which only restarts on *code* changes, so a plain
process-lifetime cache would keep serving data from whenever it was first
read even after the pipeline rewrites the parquet file underneath it.
"""
from pathlib import Path

import pandas as pd

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
LAYERS_DIR = DATA_DIR / "layers"

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


def load_zcta_geometries():
    import geopandas as gpd

    def _load():
        gdf = gpd.read_parquet(ZCTA_GEOMETRIES_PATH)
        gdf["zcta5"] = gdf["zcta5"].astype(str).str.zfill(5)
        return gdf

    return _load_if_stale(ZCTA_GEOMETRIES_PATH, "zcta_geometries", _load)


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


def layer_geojson_path(category: str) -> Path:
    return LAYERS_DIR / f"{category}.geojson"
