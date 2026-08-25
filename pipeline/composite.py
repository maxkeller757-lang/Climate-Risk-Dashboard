"""
Phase 4: composite score, a weighted power mean (Holder mean) of the 8
category percentile scores -- not a plain weighted average. Weights and
the exponent both live in composite_weights.json, not hardcoded here, so
reweighting or re-tuning the exponent later is a config change, not a
code change.

Why a power mean: a plain weighted average lets a place with several
categories in the 90s get dragged down to a mediocre composite by
unrelated low categories (e.g. Miami Beach: Flood=99, Hurricane=96, but a
plain average with the other 6 categories landed around 42). Raising each
score to a power p>1 before averaging (then taking the p-th root back to
the 0-100 scale) makes already-high scores contribute disproportionately
more, so multiple compounding hazards produce a composite that actually
reads as high-risk, without letting one single maxed-out category alone
dominate the result.

Run: pixi run python pipeline/composite.py (after every category has run)
"""
import json

import pandas as pd

from config import COMPOSITE_WEIGHTS_PATH, ZIP_SCORES_PATH
from scoring import percentile_rank, write_layer_geojson

CATEGORY = "composite"


def main():
    config = json.loads(COMPOSITE_WEIGHTS_PATH.read_text())
    exponent = config["_exponent"]["value"]
    weights = {k: v for k, v in config.items() if not k.startswith("_")}

    table = pd.read_parquet(ZIP_SCORES_PATH)

    missing = [cat for cat in weights if f"{cat}_score" not in table.columns]
    if missing:
        raise RuntimeError(
            f"Composite needs every category scored first; missing: {missing}. "
            "Run each category's pipeline module before pipeline/composite.py."
        )

    # Per-category multipliers applied before blending, for scores that
    # aren't on the same scale as the rest (see the config's comment).
    coefficients = {
        k: v
        for k, v in config.get("_score_coefficients", {}).items()
        if not k.startswith("_")
    }
    unknown = set(coefficients) - set(weights)
    if unknown:
        raise RuntimeError(f"_score_coefficients names unknown categories: {sorted(unknown)}")
    if coefficients:
        print(f"Applying score coefficients: {coefficients}")

    total_weight = sum(weights.values())
    weighted_power_sum = sum(
        (table[f"{cat}_score"].fillna(0) * coefficients.get(cat, 1.0)) ** exponent * w
        for cat, w in weights.items()
    )
    composite_raw = (weighted_power_sum / total_weight) ** (1.0 / exponent)
    table["composite_raw"] = composite_raw

    scored = percentile_rank(table[["zcta5", "composite_raw"]], raw_col="composite_raw")
    table["composite_score"] = scored["score"]

    table.to_parquet(ZIP_SCORES_PATH)
    print(
        f"Wrote composite_score for {len(table)} ZCTAs using weights={weights}, "
        f"exponent={exponent}"
    )

    write_layer_geojson(CATEGORY, "#F9A825")  # midpoint of the frontend's diverging ramp
    print(f"{CATEGORY}: done")


if __name__ == "__main__":
    main()
