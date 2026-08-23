"""
CONUS volcanic centers and their threat category, per the 2018 USGS
National Volcanic Threat Assessment (Ewert, Diefenbach & Ramsey, 2018, USGS
Scientific Investigations Report 2018-5140). USGS's own published product
for this (National Volcanic Threat Layer) ships only as an ArcGIS Pro
layer file with detailed proximal hazard zones (ballistics, pyroclastic
flow, lahar paths, etc.) -- overkill for this project's need, which is
just "is this ZCTA near an active volcanic center." So this is a small,
stable, hand-curated table of the CONUS centers from that assessment's
"Very High" and "High" threat tiers (the ones in the Cascades and around
Yellowstone/Long Valley -- matching the project brief's own framing of
where this category is relevant at all), with coordinates from USGS
Volcano Hazards Program pages.

Category -> weight is our own simple mapping, not SIR 2018-5140's literal
composite threat score (that score blends 24 hazard/exposure factors we
don't have a public per-volcano breakdown of) -- treat it as a reasonable
ordinal weighting, not a reproduction of the published index.
"""
import pandas as pd

_CATEGORY_WEIGHT = {"very_high": 1.0, "high": 0.6}

# name, lat, lon, category
_VOLCANOES = [
    ("Mount Baker", 48.7767, -121.8144, "very_high"),
    ("Glacier Peak", 48.1112, -121.1136, "very_high"),
    ("Mount Rainier", 46.8523, -121.7603, "very_high"),
    ("Mount St. Helens", 46.1912, -122.1944, "very_high"),
    ("Mount Adams", 46.2024, -121.4906, "high"),
    ("Mount Hood", 45.3736, -121.6960, "very_high"),
    ("Mount Jefferson", 44.6741, -121.7997, "high"),
    ("Three Sisters", 44.1013, -121.7690, "very_high"),
    ("Newberry Volcano", 43.7220, -121.2298, "very_high"),
    ("Crater Lake (Mount Mazama)", 42.9446, -122.1090, "very_high"),
    ("Medicine Lake", 41.5827, -121.5533, "high"),
    ("Mount Shasta", 41.4092, -122.1949, "very_high"),
    ("Lassen Volcanic Center", 40.4977, -121.5108, "very_high"),
    ("Long Valley Caldera", 37.7000, -118.8700, "very_high"),
    ("Mono-Inyo Craters", 37.8800, -119.0000, "high"),
    ("Yellowstone Caldera", 44.4280, -110.5885, "very_high"),
]


def load_volcanoes() -> pd.DataFrame:
    df = pd.DataFrame(_VOLCANOES, columns=["name", "lat", "lon", "category"])
    df["weight"] = df["category"].map(_CATEGORY_WEIGHT)
    return df
