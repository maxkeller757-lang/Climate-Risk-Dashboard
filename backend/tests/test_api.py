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
    # 99999 is reserved/unassigned -- not in the crosswalk and not a ZCTA.
    # Should 404 rather than fabricate a nearest match.
    res = client.get("/api/zip/99999")
    assert res.status_code == 404


def test_zcta_detail_matches_zip_detail_for_direct_match():
    zip_res = client.get("/api/zip/73160").json()
    zcta_res = client.get("/api/zcta/73160").json()
    assert zip_res["composite_score"] == zcta_res["composite_score"]
    assert zip_res["categories"] == zcta_res["categories"]
    assert zcta_res["zip"] is None


def test_layer_top_zones_shape_and_state():
    res = client.get("/api/layer/hurricane/top")
    assert res.status_code == 200
    body = res.json()
    assert body["category"] == "hurricane"
    assert len(body["zones"]) == 3
    for zone in body["zones"]:
        assert len(zone["zcta"]) == 5 and zone["zcta"].isdigit()
        # Every real ZCTA carries a state, and the table is useless without it.
        assert zone["state"] is not None and len(zone["state"]) == 2
        assert isinstance(zone["population"], int) and zone["population"] >= 0
        assert 0 <= zone["score"] <= 100
    # Descending by score.
    scores = [z["score"] for z in body["zones"]]
    assert scores == sorted(scores, reverse=True)


def test_layer_top_zones_county_present_when_geometry_has_one():
    # County comes from a dominant-area overlay against Census counties,
    # same mechanism as the gap-area state attribution -- every real ZCTA
    # should get one.
    body = client.get("/api/layer/composite/top?limit=10").json()
    assert all(z["county"] for z in body["zones"])


def test_layer_top_zones_score_precision_distinguishes_near_ties():
    # 1dp collapsed several distinct top scores to an identical "100.0",
    # which read as a tie that wasn't real (percentile_rank derives score
    # from raw via a strictly monotonic map, so equal scores only occur
    # where the raw metric hits a genuine ceiling). 3dp still wasn't
    # enough -- hurricane has two ZCTAs in its top 25 that agree to 3
    # decimals and only separate at the 4th -- so this checks at 5dp.
    body = client.get("/api/layer/hurricane/top").json()
    scores = [z["score"] for z in body["zones"]]
    assert len(set(scores)) == len(scores)


def test_layer_top_zones_5dp_separates_the_near_duplicate_case():
    # The concrete case that motivated 5dp: 28512 (99.840351) and 27943
    # (99.839530) both round to 99.840 at 3dp -- indistinguishable and
    # wrongly reading as a tie -- but are genuinely different scores.
    body = client.get("/api/layer/hurricane/top?limit=25").json()
    by_zcta = {z["zcta"]: z["score"] for z in body["zones"]}
    assert by_zcta["28512"] == pytest.approx(99.84035, abs=1e-5)
    assert by_zcta["27943"] == pytest.approx(99.83953, abs=1e-5)
    assert by_zcta["28512"] != by_zcta["27943"]


def test_layer_top_zones_tiebreak_is_population_then_zcta():
    # flood has a large genuine tie block (21 ZCTAs at 100% SFHA area) --
    # exercise the real tiebreak path, not just the common case.
    #
    # The API only exposes population rounded to the nearest person, so
    # two rows can display the same population without actually being tied
    # on the endpoint's real (unrounded) sort key -- e.g. 1.885 and 1.835
    # both display as "2". Grouping by the rounded field to check "zcta5
    # ascending within a population tie" is therefore not a valid check;
    # it produced a false failure on exactly that case (72377/97432/34487
    # all round to population 2 but have distinct precise values). Ground
    # truth for the real tiebreak column has to come from the same source
    # the endpoint itself sorts on.
    import geopandas as gpd

    real_pop = gpd.read_parquet(
        Path(__file__).resolve().parents[2] / "data" / "zcta_geometries_render.parquet"
    ).set_index("zcta5")["population"]

    body = client.get("/api/layer/flood/top?limit=25").json()
    tied = [z for z in body["zones"] if z["score"] == body["zones"][0]["score"]]
    assert len(tied) > 1, "expected a genuine tie block in flood's top scores"

    precise_pops = [real_pop[z["zcta"]] for z in tied]
    assert precise_pops == sorted(precise_pops, reverse=True)
    # Within any *exact* population tie (on the real, unrounded value),
    # zcta5 must be ascending.
    for pop in set(precise_pops):
        zctas = [z["zcta"] for z, p in zip(tied, precise_pops) if p == pop]
        assert zctas == sorted(zctas)


def test_layer_top_zones_excludes_gap_areas():
    # "The three worst places for wildfire" listing unnamed patches of
    # national forest would be useless; gap areas must never appear.
    for category in ("wildfire", "flood", "composite"):
        body = client.get(f"/api/layer/{category}/top?limit=25").json()
        assert all(not z["zcta"].startswith("NOZIP-") for z in body["zones"])


def test_layer_top_zones_respects_limit():
    body = client.get("/api/layer/flood/top?limit=5").json()
    assert len(body["zones"]) == 5


def test_layer_top_zones_unknown_category_404s():
    res = client.get("/api/layer/not_a_real_category/top")
    assert res.status_code == 404


def test_unknown_layer_category_404s():
    res = client.get("/api/layer/not_a_real_category")
    assert res.status_code == 404


def test_generated_layer_returns_geojson():
    res = client.get("/api/layer/severe_convective")
    assert res.status_code == 200
    body = res.json()
    assert body["type"] == "FeatureCollection"
    assert len(body["features"]) > 30000  # full CONUS ZCTA coverage
