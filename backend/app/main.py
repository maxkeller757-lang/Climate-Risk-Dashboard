"""
FastAPI app serving pre-computed hazard scores. No live geoprocessing here
-- every response reads data the offline pipeline (pipeline/) already wrote.

Run: pixi run uvicorn backend.app.main:app --reload --port 8003
"""
from fastapi import FastAPI, HTTPException, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.middleware.gzip import GZipMiddleware
from fastapi.responses import FileResponse

import json

import pandas as pd

from .data_access import (
    NO_ZIP_PREFIX,
    layer_geojson_path,
    load_zcta_geometries,
    load_zip_scores,
)
from .layers_meta import LAYERS, LAYERS_BY_CATEGORY
from .zip_lookup import classify_zip_format, resolve_zcta

_ZIP_FORMAT_ERRORS = {
    "empty": "Zip code is required.",
    "whitespace": "Zip code must not contain leading or trailing whitespace.",
    "non_numeric": "Zip code must contain only digits 0-9.",
    "too_short": "Zip code must be exactly 5 digits (too short).",
    "too_long": "Zip code must be exactly 5 digits (too long).",
}

# Well-formed ZIPs that still can't be scored. Kept distinct from each
# other because "we don't cover that area" and "that isn't a real ZIP" are
# different answers, and the search box should be able to say which.
_ZIP_RESOLVE_ERRORS = {
    "unknown_zip": "{zipcode} isn't a recognized US zip code.",
    "no_zcta": (
        "{zipcode} is a valid zip code, but the Census defines no ZCTA for it, "
        "so there's no area to score."
    ),
    "outside_conus": (
        "{zipcode} is outside the contiguous US. This dashboard covers CONUS only."
    ),
}

app = FastAPI(title="Zip-Code Climate & Hazard Risk Dashboard API")

# Local dev only: Vite's default port. Tighten this before any real deploy.
app.add_middleware(
    CORSMiddleware,
    allow_origins=["http://localhost:5173", "http://127.0.0.1:5173"],
    allow_methods=["GET"],
    allow_headers=["*"],
)

# Compresses the small dynamic JSON endpoints (/api/layers, /api/zip/...)
# on the fly -- cheap, since those responses are a few KB. It does NOT
# touch /api/layer/{category}: FileResponse sends large files via uvicorn's
# zero-copy `pathsend` extension, which hands the file straight to the OS
# and never passes through body-based middleware like this one. That's
# handled separately below with a file pre-gzipped at pipeline build time
# (compressing the real 34MB payload live would cost 1-3s of blocking CPU
# per request). No brotli here: that needs a third-party ASGI middleware
# (e.g. brotli-asgi) since Starlette only ships gzip.
app.add_middleware(GZipMiddleware, minimum_size=1000)


@app.get("/api/layers")
def get_layers():
    return LAYERS


@app.get("/api/layer/{category}")
def get_layer(category: str, request: Request):
    if category not in LAYERS_BY_CATEGORY:
        raise HTTPException(404, f"Unknown layer category: {category}")
    path = layer_geojson_path(category)
    if not path.exists():
        raise HTTPException(
            404,
            f"Layer '{category}' has not been generated yet by the pipeline.",
        )

    # Serve the pre-gzipped sibling (~25% of the size) when the client
    # supports it -- every browser does. GZipMiddleware can't do this job
    # itself; see the comment on its registration above.
    accepts_gzip = "gzip" in request.headers.get("accept-encoding", "")
    gz_path = path.with_name(path.name + ".gz")
    if accepts_gzip and gz_path.exists():
        return FileResponse(
            gz_path,
            media_type="application/geo+json",
            headers={"Content-Encoding": "gzip"},
        )
    return FileResponse(path, media_type="application/geo+json")


@app.get("/api/zip/{zipcode}/exists")
def zip_exists(zipcode: str):
    reason = classify_zip_format(zipcode)
    if reason:
        return {"exists": False, "reason": reason, "message": _ZIP_FORMAT_ERRORS[reason]}
    zcta, reason = resolve_zcta(zipcode)
    if zcta is None:
        return {
            "exists": False,
            "reason": reason,
            "message": _ZIP_RESOLVE_ERRORS[reason].format(zipcode=zipcode),
        }
    return {"exists": True}


@app.get("/api/zcta/{zcta5}/geometry")
def get_zcta_geometry(zcta5: str):
    """Single-ZCTA polygon, used by the frontend to zoom/pan to and outline
    a searched zip -- independent of whichever category layer is active."""
    gdf = load_zcta_geometries()
    row = gdf.loc[gdf["zcta5"] == zcta5]
    if row.empty:
        raise HTTPException(404, f"No geometry for ZCTA {zcta5}.")
    feature = json.loads(row.iloc[[0]].to_json())["features"][0]
    return feature


@app.get("/api/layer/{category}/top")
def get_layer_top_zones(category: str, limit: int = 3):
    """Highest-scoring zones for one layer, with the county/state and an
    apportioned population estimate for each.

    Shown when the user's most recent action was picking a layer rather
    than a polygon: at that moment the question is "where is this hazard
    worst", which a single polygon's breakdown can't answer.

    No-ZIP gap areas are excluded. They are real land and carry real
    scores, but "the three worst places for wildfire" listing three
    unnamed patches of national forest would be useless to someone
    reading it, and gap areas are numerous enough at the top of some
    layers to crowd out every actual zip code.

    Ordering: score descending, ties broken by population descending, then
    zcta5 ascending. A raw-metric tiebreak was tried first and turned out
    to be dead code -- percentile_rank() derives score from raw via
    rank(pct=True), a strictly monotonic map, so two rows can never share
    a score while differing in raw. Real ties only occur where the raw
    metric itself hits a hard ceiling (e.g. 21 ZCTAs at 100% of area in a
    flood zone), and for those, population is the tiebreak that means
    something: more people exposed ranks first. zcta5 makes the remainder
    fully deterministic.
    """
    if category not in LAYERS_BY_CATEGORY:
        raise HTTPException(404, f"Unknown layer category: {category}")
    limit = max(1, min(limit, 25))

    score_col = f"{category}_score"
    scores = load_zip_scores()
    if score_col not in scores.columns:
        raise HTTPException(404, f"Layer '{category}' has not been scored yet.")

    real = scores[~scores["zcta5"].str.startswith(NO_ZIP_PREFIX)]
    attrs = load_zcta_geometries()[["zcta5", "state", "county", "population"]]
    merged = real.merge(attrs, on="zcta5", how="left")
    merged["population"] = merged["population"].fillna(0)

    top = merged.sort_values(
        [score_col, "population", "zcta5"], ascending=[False, False, True]
    ).head(limit)
    return {
        "category": category,
        "name": LAYERS_BY_CATEGORY[category]["name"],
        "zones": [
            {
                "zcta": row.zcta5,
                "county": None if pd.isna(row.county) else row.county,
                "state": None if pd.isna(row.state) else row.state,
                "population": int(round(row.population)),
                # 5dp: the top of a percentile scale is dense enough that
                # 1dp collapses distinct ZCTAs to an identical "100.0",
                # which reads as a tie that isn't really there. 3dp still
                # wasn't enough -- e.g. hurricane has two ZCTAs in its top
                # 25 that agree to 3 decimals and only separate at the 4th.
                "score": round(float(getattr(row, score_col)), 5),
            }
            for row in top.itertuples()
        ],
    }


def _build_zcta_detail(zcta: str) -> dict:
    scores = load_zip_scores()
    row = scores.loc[scores["zcta5"] == zcta]
    if row.empty:
        raise HTTPException(404, f"No score data for ZCTA {zcta}.")
    row = row.iloc[0]

    categories = []
    for layer in LAYERS:
        cat = layer["category"]
        if cat == "composite":
            continue
        score_col, raw_col = f"{cat}_score", f"{cat}_raw"
        if score_col not in row or row[score_col] != row[score_col]:  # NaN check
            continue  # category not yet computed by the pipeline
        categories.append(
            {
                "name": layer["name"],
                "category": cat,
                "score": round(float(row[score_col]), 1),
                "raw_metric": float(row[raw_col]) if raw_col in row else None,
                "color": layer["color"],
            }
        )

    composite_score = None
    if "composite_score" in row and row["composite_score"] == row["composite_score"]:
        composite_score = round(float(row["composite_score"]), 1)

    return {"zcta": zcta, "composite_score": composite_score, "categories": categories}


@app.get("/api/zip/{zipcode}")
def get_zip(zipcode: str):
    reason = classify_zip_format(zipcode)
    if reason:
        raise HTTPException(400, _ZIP_FORMAT_ERRORS[reason])

    zcta, reason = resolve_zcta(zipcode)
    if zcta is None:
        raise HTTPException(404, _ZIP_RESOLVE_ERRORS[reason].format(zipcode=zipcode))

    return {"zip": zipcode, **_build_zcta_detail(zcta)}


@app.get("/api/zcta/{zcta5}")
def get_zcta(zcta5: str):
    """Same shape as /api/zip/{zipcode}, keyed directly by ZCTA5 -- used by
    the frontend's click-on-map-polygon inspector, which reads the zcta5
    property straight off the rendered layer feature rather than going
    through zip->ZCTA resolution."""
    return {"zip": None, **_build_zcta_detail(zcta5)}
