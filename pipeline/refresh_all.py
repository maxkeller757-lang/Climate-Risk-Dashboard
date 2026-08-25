"""
Full pipeline refresh: rerun every ingestion step end-to-end so the project
is reproducible from raw sources, not a one-off snapshot (Phase 7).

Run: pixi run python pipeline/refresh_all.py

Note: this is a long run (multiple large downloads, ~3,100 live queries
each for Flood and Drought, 10 years of gridMET for Heat). Each category
module caches its raw source data per-county/per-year, so re-running after
a partial failure only re-fetches what's missing.
"""
import os

import air_quality
import build_render_geometries
import build_zip_crosswalk
import composite
import drought
import fill_nozip_scores
import flood
import heat
import hurricane
import seismic
import severe_convective
import subdivide_large_gaps
import verify_layers
import wildfire
import winter_weather
from fetch_zcta_geometries import main as fetch_zcta_geometries
from layer_writer import write_all_layers

# Categories only update zip_scores here; layer GeoJSON is written once at
# the end, because a layer cannot be rendered until every polygon has a
# score for every category (see SKIP_LAYER_WRITE in scoring.py).
CATEGORY_STEPS = [
    ("Severe Convective", severe_convective.main),
    ("Winter Weather", winter_weather.main),
    ("Flood", flood.main),
    ("Wildfire", wildfire.main),
    ("Hurricane", hurricane.main),
    ("Drought", drought.main),
    ("Extreme Heat", heat.main),
    ("Seismic", seismic.main),
    ("Air Quality", air_quality.main),
]


def main():
    print("\n=== ZCTA geometries ===")
    fetch_zcta_geometries()

    # Must run before the render build and before any scoring: it splits
    # gap areas at state lines and by size, changing both the polygon set
    # and the NOZIP ids everything downstream is keyed on.
    print("\n=== Subdivide oversized gap areas ===")
    subdivide_large_gaps.main()

    print("\n=== Render geometries ===")
    build_render_geometries.main()

    print("\n=== ZIP -> ZCTA crosswalk ===")
    build_zip_crosswalk.main()

    os.environ["SKIP_LAYER_WRITE"] = "1"
    for label, step in CATEGORY_STEPS:
        print(f"\n=== {label} ===")
        step()

    print("\n=== Fill missing scores from neighbours ===")
    fill_nozip_scores.main()

    print("\n=== Composite ===")
    composite.main()

    del os.environ["SKIP_LAYER_WRITE"]
    print("\n=== Write layers ===")
    write_all_layers()

    print("\n=== Verify ===")
    verify_layers.main()


if __name__ == "__main__":
    main()
