"""
Phase 8 API tests: valid/invalid/malformed zips, the no-ZCTA-match
fallback case, and basic layer/detail endpoint shape checks. Runs against
whatever the pipeline has actually produced in data/ -- no mocking, since
the whole point of this API is "reads real pre-computed data."

Run: pixi run python -m pytest backend/tests/test_api.py -v
"""
import sys
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))
from backend.app.main import app  # noqa: E402

client = TestClient(app)


def test_layers_lists_all_categories():
    res = client.get("/api/layers")
    assert res.status_code == 200
    data = res.json()
    categories = {layer["category"] for layer in data}
    assert categories == {
        "severe_convective",
        "winter_weather",
        "flood",
        "wildfire",
        "hurricane",
        "drought",
        "heat",
        "seismic",
        "air_quality",
        "composite",
    }


def test_valid_zip_known_high_tornado_risk():
    # Moore, OK -- well inside tornado alley, should score high on
    # severe_convective specifically (not just present).
    res = client.get("/api/zip/73160")
    assert res.status_code == 200
    data = res.json()
    assert data["zcta"] == "73160"
    sc = next(c for c in data["categories"] if c["category"] == "severe_convective")
    assert sc["score"] > 80


def test_zip_exists_true_for_real_zip():
    res = client.get("/api/zip/73160/exists")
    assert res.status_code == 200
    assert res.json()["exists"] is True


def test_zip_exists_false_for_malformed():
    res = client.get("/api/zip/abc/exists")
    assert res.status_code == 200
    assert res.json()["exists"] is False


def test_malformed_zip_detail_returns_400():
    res = client.get("/api/zip/abc")
    assert res.status_code == 400


def test_unmapped_zip_returns_404_not_silent_guess():
    # A well-formed 5-digit code very unlikely to be a real ZCTA5 (99999 is
    # reserved/unassigned). v1 zip->ZCTA resolution only does a direct
    # match (see zip_lookup.py); this should 404, not fabricate a nearest
    # match.
    res = client.get("/api/zip/99999")
    assert res.status_code == 404


def test_zcta_detail_matches_zip_detail_for_direct_match():
    zip_res = client.get("/api/zip/73160").json()
    zcta_res = client.get("/api/zcta/73160").json()
    assert zip_res["composite_score"] == zcta_res["composite_score"]
    assert zip_res["categories"] == zcta_res["categories"]
    assert zcta_res["zip"] is None


def test_unknown_layer_category_404s():
    res = client.get("/api/layer/not_a_real_category")
    assert res.status_code == 404


def test_generated_layer_returns_geojson():
    res = client.get("/api/layer/severe_convective")
    assert res.status_code == 200
    body = res.json()
    assert body["type"] == "FeatureCollection"
    assert len(body["features"]) > 30000  # full CONUS ZCTA coverage
