"""
Write all nine layer GeoJSONs in one pass.

Kept separate from the category modules because a layer can only be
written once *every* polygon has a score for that category -- which isn't
true until the last category and the neighbour-fill step have run. Each
category's colour lives with its module; this is the one place that
knows the full set.

Run: pixi run python pipeline/layer_writer.py
"""
from scoring import write_layer_geojson

LAYER_COLORS = {
    "severe_convective": "#7B2D8E",
    "flood": "#1E88A8",
    "wildfire": "#D32F2F",
    "hurricane": "#00707A",
    "winter_weather": "#6EC6E8",
    "drought": "#B8860B",
    "heat": "#E85D04",
    "seismic": "#8B5E3C",
    # Midpoint of the frontend's green->yellow->red diverging ramp; the
    # frontend supplies the full ramp for this one (see colorRamps.ts).
    "composite": "#F9A825",
}


def write_all_layers() -> None:
    for category, color in LAYER_COLORS.items():
        write_layer_geojson(category, color)


if __name__ == "__main__":
    write_all_layers()
