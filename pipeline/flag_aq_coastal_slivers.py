"""
Diagnostic/review tool -- NOT part of refresh_all.py.

Flags no-ZIP gap polygons that likely deserve removal from the Air
Quality layer: small coastal slivers left behind by clip_gap_water.py
whose air_quality_score is implausibly high relative to their own raw
metric and their real-ZCTA neighbours.

Root cause: spatial_smooth() (scoring.py) finds queen-contiguity
neighbours across the *entire* ZCTA geometry set, gap polygons included.
Water-clipping (clip_gap_water.py) breaks a coastline's gap area into many
small adjacent slivers; if the census tract overlapping one of those
slivers happens to carry a spurious/edge-effect PM2.5 estimate, one pass
of smoothing spreads that value to every other tiny sliver touching it --
even slivers whose own true metric (avg_exceedance_days) is 0. Confirmed
directly: 225 of the 226 flagged polygons below have avg_exceedance_days
< 0.5 (essentially perfect air quality) yet a percentile score of ~100
(worst in CONUS), while every real ZCTA touching them scores ~23.

Detection method (per user's own suggested approach): a gap polygon
counts as a "significant coast" candidate if clip_gap_water.py removed
more than 10% of its area as open water, AND its air_quality_score
exceeds the mean score of its real (non-gap) touching ZCTA neighbours by
more than 25 points.

This script does NOT delete anything or touch score data. It only:
  1. Writes the candidate zcta5 list to data/aq_coastal_sliver_candidates.csv
     for a later removal step to reuse without recomputing.
  2. Patches data/layers/air_quality.geojson (and .geojson.gz) in place,
     adding a `review_flag: true` property to just those features, so
     they render bright green in the Air Quality layer (see
     frontend/src/components/MapView.tsx's fillColorExpression) for the
     user to visually confirm before anything is removed. No other layer
     file is touched.

Run: pixi run python pipeline/flag_aq_coastal_slivers.py
"""
import gzip
import json
import shutil

import geopandas as gpd
import pandas as pd

from config import (
    DATA_DIR,
    EQUAL_AREA_CRS,
    LAYERS_DIR,
    NO_ZIP_PREFIX,
    ZCTA_GEOMETRIES_PATH,
    ZCTA_RENDER_GEOMETRIES_PATH,
    ZIP_SCORES_PATH,
)

CANDIDATES_PATH = DATA_DIR / "aq_coastal_sliver_candidates.csv"

# A gap polygon must have lost more than this fraction of its analysis-
# geometry area to water clipping to count as "has a significant coast".
COASTAL_FRAC_THRESHOLD = 0.10
# ...and its own score must exceed the mean of its real-ZCTA neighbours'
# scores by more than this many points to count as anomalous.
EXCESS_SCORE_THRESHOLD = 25
# Same buffer approach as fill_nozip_scores.py's neighbour search, widened
# slightly to reliably cross a thin sliver to the nearest real ZCTA.
NEIGHBOR_TOLERANCE_M = 200

REVIEW_COLOR = "#39FF14"


def find_candidates() -> pd.DataFrame:
    analysis = gpd.read_parquet(ZCTA_GEOMETRIES_PATH)
    render = gpd.read_parquet(ZCTA_RENDER_GEOMETRIES_PATH)
    scores = pd.read_parquet(ZIP_SCORES_PATH)
    scores["zcta5"] = scores["zcta5"].astype(str)

    is_gap = analysis["zcta5"].astype(str).str.startswith(NO_ZIP_PREFIX)
    gaps_analysis = analysis[is_gap].to_crs(EQUAL_AREA_CRS)
    gaps_render = render[render["zcta5"].isin(gaps_analysis["zcta5"])].to_crs(EQUAL_AREA_CRS)

    a_area = gaps_analysis.set_index("zcta5").geometry.area
    r_area = gaps_render.set_index("zcta5").geometry.area
    coastal_frac = (1 - (r_area / a_area).reindex(a_area.index)).fillna(1.0)

    real = analysis[~is_gap].to_crs(EQUAL_AREA_CRS).merge(
        scores[["zcta5", "air_quality_score", "air_quality_raw"]], on="zcta5", how="inner"
    )
    probe = gaps_analysis[["zcta5", "geometry"]].copy()
    probe["geometry"] = probe.geometry.buffer(NEIGHBOR_TOLERANCE_M)
    pairs = gpd.sjoin(
        probe,
        real[["zcta5", "geometry"]].rename(columns={"zcta5": "neighbor"}),
        how="left",
        predicate="intersects",
    ).dropna(subset=["neighbor"])

    real_score = real.set_index("zcta5")["air_quality_score"]
    pairs["neighbor_score"] = pairs["neighbor"].map(real_score)
    neighbor_mean = pairs.groupby("zcta5")["neighbor_score"].mean()

    gap_scores = scores[scores["zcta5"].isin(gaps_analysis["zcta5"])].set_index("zcta5")[
        ["air_quality_score", "air_quality_raw"]
    ]
    result = pd.DataFrame(
        {
            "coastal_frac": coastal_frac,
            "own_score": gap_scores["air_quality_score"],
            "own_raw": gap_scores["air_quality_raw"],
            "neighbor_mean_score": neighbor_mean,
        }
    ).dropna(subset=["own_score"])
    result["excess"] = result["own_score"] - result["neighbor_mean_score"]

    # Only polygons still present in the render layer matter here -- a gap
    # fully dissolved by clip_gap_water.py already doesn't draw on the map.
    visible = result[result.index.isin(gaps_render["zcta5"])]
    candidates = visible[
        (visible["coastal_frac"] > COASTAL_FRAC_THRESHOLD)
        & (visible["excess"] > EXCESS_SCORE_THRESHOLD)
    ]
    return candidates.sort_values("excess", ascending=False)


def flag_layer(candidate_ids: set[str]) -> None:
    path = LAYERS_DIR / "air_quality.geojson"
    gz_path = LAYERS_DIR / "air_quality.geojson.gz"
    data = json.loads(path.read_text(encoding="utf-8"))

    flagged = 0
    for feature in data["features"]:
        if feature["properties"].get("zcta5") in candidate_ids:
            feature["properties"]["review_flag"] = True
            feature["properties"]["color"] = REVIEW_COLOR
            flagged += 1
    if flagged != len(candidate_ids):
        raise RuntimeError(
            f"Flagged {flagged} feature(s) but had {len(candidate_ids)} candidate id(s) -- "
            "some candidates weren't found in air_quality.geojson."
        )

    tmp_path = path.with_name(path.name + ".tmp")
    tmp_path.write_text(json.dumps(data), encoding="utf-8")
    shutil.move(tmp_path, path)

    with open(path, "rb") as f_in, gzip.open(gz_path, "wb") as f_out:
        shutil.copyfileobj(f_in, f_out)

    print(f"Flagged {flagged} feature(s) bright green ({REVIEW_COLOR}) in {path.name}")


def main():
    candidates = find_candidates()
    print(f"{len(candidates)} candidate coastal sliver(s) found")
    print(candidates.head(20))

    candidates.to_csv(CANDIDATES_PATH)
    print(f"Wrote candidate list to {CANDIDATES_PATH}")

    flag_layer(set(candidates.index))


if __name__ == "__main__":
    main()
