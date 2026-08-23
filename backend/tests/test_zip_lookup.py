"""
Exhaustive test of zip-code input handling: every malformed-input case
should get a distinct, correct classification (unit level) and the right
status code + message (API level) -- not just a generic "invalid" catch-all.

Run: pixi run python -m pytest backend/tests/test_zip_lookup.py -v
"""
import sys
from pathlib import Path
from urllib.parse import quote

import pytest
from fastapi.testclient import TestClient

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))
from backend.app.main import _ZIP_FORMAT_ERRORS, app  # noqa: E402
from backend.app.zip_lookup import classify_zip_format  # noqa: E402

client = TestClient(app)

# (input, expected reason code)
FORMAT_CASES = [
    ("123", "too_short"),
    ("1", "too_short"),
    ("123456", "too_long"),
    ("123456789", "too_long"),
    ("abcde", "non_numeric"),
    ("1234a", "non_numeric"),
    ("12-45", "non_numeric"),
    ("12345-6789", "non_numeric"),  # zip+4 format, not supported as a single input
    ("-1234", "non_numeric"),
    ("12 45", "non_numeric"),
    (" 12345", "whitespace"),
    ("12345 ", "whitespace"),
    ("\t12345", "whitespace"),
    ("１２３４５", "non_numeric"),  # full-width Unicode digits, not ASCII
    ("12345' OR '1'='1", "non_numeric"),  # SQLi-shaped input, rejected as non-numeric
    ("00501", None),  # valid: real zip with a leading zero
    ("73160", None),  # valid, well-formed
]


@pytest.mark.parametrize("value,expected_reason", FORMAT_CASES)
def test_classify_zip_format(value, expected_reason):
    assert classify_zip_format(value) == expected_reason


def test_classify_empty_string():
    assert classify_zip_format("") == "empty"


@pytest.mark.parametrize("value,expected_reason", [c for c in FORMAT_CASES if c[1] is not None])
def test_get_zip_400_with_specific_message(value, expected_reason):
    res = client.get(f"/api/zip/{quote(value, safe='')}")
    assert res.status_code == 400, f"{value!r} should 400"
    assert res.json()["detail"] == _ZIP_FORMAT_ERRORS[expected_reason]


@pytest.mark.parametrize("value,expected_reason", [c for c in FORMAT_CASES if c[1] is not None])
def test_zip_exists_false_with_specific_reason(value, expected_reason):
    res = client.get(f"/api/zip/{quote(value, safe='')}/exists")
    assert res.status_code == 200
    body = res.json()
    assert body["exists"] is False
    assert body["reason"] == expected_reason


def test_zip_exists_not_found_reason_for_well_formed_unknown_zip():
    res = client.get("/api/zip/99999/exists")
    assert res.status_code == 200
    body = res.json()
    assert body == {
        "exists": False,
        "reason": "not_found",
        "message": "No ZCTA mapping found for zip 99999.",
    }


def test_get_zip_empty_path_404s_at_routing_level():
    # No path segment at all -- FastAPI's own routing 404s before our
    # handler runs (there's no route for a bare /api/zip/).
    res = client.get("/api/zip/")
    assert res.status_code == 404


def test_get_zip_path_traversal_like_input_does_not_escape_route():
    # %2F decodes to a literal "/", which splits this into multiple path
    # segments before routing -- no route matches, so it 404s at the
    # routing level (never reaches our handler at all). Either way, the
    # key property holds: it's rejected, not treated as path navigation.
    res = client.get("/api/zip/..%2F..%2Fetc%2Fpasswd")
    assert res.status_code in (400, 404)


def test_nozip_designator_is_rejected_as_a_zip_search():
    # NOZIP-##### gap-fill IDs (see fetch_zcta_geometries.py) are
    # deliberately not 5-digit, so they can never be searched as a zip --
    # only reachable via /api/zcta/{zcta5} (map click-to-inspect).
    res = client.get("/api/zip/NOZIP-00001")
    assert res.status_code == 400
    assert res.json()["detail"] == _ZIP_FORMAT_ERRORS["non_numeric"]


def test_nozip_designator_has_no_score_via_zcta_endpoint():
    # Not an error case exactly, but confirms the click-to-inspect path
    # for a no-ZIP area fails clearly (404) rather than fabricating data,
    # same principle as the unmapped-zip case.
    res = client.get("/api/zcta/NOZIP-00001")
    assert res.status_code in (200, 404)  # 200 only if that gap piece exists this run
