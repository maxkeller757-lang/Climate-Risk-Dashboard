"""
FastAPI app serving pre-computed hazard scores. No live geoprocessing here
-- every response reads data the offline pipeline (pipeline/) already wrote.

Run: pixi run uvicorn backend.app.main:app --reload --port 8000
"""
from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse

import json

from .data_access import layer_geojson_path, load_zcta_geometries, load_zip_scores
from .layers_meta import LAYERS, LAYERS_BY_CATEGORY
from .zip_lookup import classify_zip_format, resolve_zcta

_ZIP_FORMAT_ERRORS = {
    "empty": "Zip code is required.",
    "whitespace": "Zip code must not contain leading or trailing whitespace.",
    "non_numeric": "Zip code must contain only digits 0-9.",
    "too_short": "Zip code must be exactly 5 digits (too short).",
    "too_long": "Zip code must be exactly 5 digits (too long).",
}

app = FastAPI(title="Zip-Code Climate & Hazard Risk Dashboard API")

# Local dev only: Vite's default port. Tighten this before any real deploy.
app.add_middleware(
    CORSMiddleware,
    allow_origins=["http://localhost:5173", "http://127.0.0.1:5173"],
    allow_methods=["GET"],
    allow_headers=["*"],
)


@app.get("/api/layers")
def get_layers():
    return LAYERS


@app.get("/api/layer/{category}")
def get_layer(category: str):
    if category not in LAYERS_BY_CATEGORY:
        raise HTTPException(404, f"Unknown layer category: {category}")
    path = layer_geojson_path(category)
    if not path.exists():
        raise HTTPException(
            404,
            f"Layer '{category}' has not been generated yet by the pipeline.",
        )
    return FileResponse(path, media_type="application/geo+json")


@app.get("/api/zip/{zipcode}/exists")
def zip_exists(zipcode: str):
    reason = classify_zip_format(zipcode)
    if reason:
        return {"exists": False, "reason": reason, "message": _ZIP_FORMAT_ERRORS[reason]}
    zcta = resolve_zcta(zipcode)
    if zcta is None:
        return {"exists": False, "reason": "not_found", "message": f"No ZCTA mapping found for zip {zipcode}."}
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

    zcta = resolve_zcta(zipcode)
    if zcta is None:
        # See zip_lookup.py: v1 only resolves direct zip==ZCTA5 matches.
        raise HTTPException(
            404,
            f"No ZCTA mapping found for zip {zipcode}. "
            "PO-box-only and split zips aren't covered yet (Phase 5 TODO).",
        )

    return {"zip": zipcode, **_build_zcta_detail(zcta)}


@app.get("/api/zcta/{zcta5}")
def get_zcta(zcta5: str):
    """Same shape as /api/zip/{zipcode}, keyed directly by ZCTA5 -- used by
    the frontend's click-on-map-polygon inspector, which reads the zcta5
    property straight off the rendered layer feature rather than going
    through zip->ZCTA resolution."""
    return {"zip": None, **_build_zcta_detail(zcta5)}
