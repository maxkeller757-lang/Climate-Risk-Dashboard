"""
Hurricane / Tropical category: wind-speed-weighted exposure from NOAA
HURDAT2 track point proximity to ZCTA centroids, 2015-2024.

Weight is max_wind^2 (knots), not max_wind linearly -- wind damage
potential scales roughly with the square (structural loading) to cube
(kinetic energy) of wind speed, so a linear weight would understate how
much worse a major hurricane is than a tropical storm. Distance decay is
linear out to 150mi (roughly the damaging-wind radius of a large
hurricane), via spatial.distance_weighted_score.

After percentile ranking, scores get an S-curve contrast stretch
(scoring.contrast_stretch) that pushes already-high (coastal) ZCTAs higher
and already-low (interior) ZCTAs lower -- the raw distance-weighted
exposure already separates coast from interior, but a plain percentile
rank spreads that separation out linearly across the full 0-100 range; the
stretch makes the map read as more sharply concentrated on the coast,
closer to how hurricane risk actually presents (a fairly sharp coastal
falloff, not a gradual inland taper), without pulling any new data.

On top of that, the score is further divided by (1 + K * coast_distance_miles)
(spatial.coast_distance_miles, K below) -- a coastal ZCTA (distance ~0) is
essentially untouched, while an inland ZCTA's score shrinks the farther it
is from the coast, even if the wind-decay model alone gave it a
moderate/high score (e.g. a storm that curved inland before the model's
150mi radius cut it off). This is a deliberately blunt, arbitrary-constant
knob (not fit to any data) requested to push the map to read as more
concentrated right on the shore; see the K comment below for what it does
numerically.

Run: pixi run python pipeline/hurricane.py
"""
import geopandas as gpd

from config import ZCTA_GEOMETRIES_PATH
from scoring import contrast_stretch, percentile_rank, upsert_zip_scores, write_layer_geojson
from sources.hurdat2 import load_track_points
from spatial import coast_distance_miles, distance_weighted_score

CATEGORY = "hurricane"
COLOR = "#00707A"
RADIUS_MILES = 150.0
CONTRAST_POWER = 2.5
# score /= (1 + COAST_DISTANCE_K * miles_from_coast). At K=0.01: a ZCTA
# 100mi inland gets its score halved, 300mi inland quartered, 500mi inland
# cut to ~1/6 -- roughly matching how quickly hurricanes actually weaken
# after landfall, though it's a chosen constant, not derived from data.
COAST_DISTANCE_K = 0.01


def main():
    zcta = gpd.read_parquet(ZCTA_GEOMETRIES_PATH)

    print("Loading HURDAT2 track points...")
    points = load_track_points()
    points["wind_weight"] = points["max_wind"] ** 2
    print(f"{len(points)} track points loaded")

    raw = distance_weighted_score(zcta, points, weight_col="wind_weight", radius_miles=RADIUS_MILES)
    scored = percentile_rank(raw, raw_col="exposure_score")
    scored["score"] = contrast_stretch(scored["score"], power=CONTRAST_POWER)

    print("Applying coast-distance concentration...")
    coast_dist = coast_distance_miles(zcta)
    scored = scored.merge(coast_dist, on="zcta5")
    scored["score"] = scored["score"] / (1 + COAST_DISTANCE_K * scored["coast_distance_miles"])

    upsert_zip_scores(CATEGORY, scored, raw_col="exposure_score")
    write_layer_geojson(CATEGORY, COLOR)
    print(f"{CATEGORY}: done")


if __name__ == "__main__":
    main()
