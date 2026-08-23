"""
Regenerates frontend/src/basemapStyle.json: OpenFreeMap's "liberty" style
(https://openfreemap.org, free, no API key, no rate limit) trimmed down to a
minimal layer set that still keeps interstate highways and park/forest/
water/urban landuse symbology, per the project's "minimalistic but not
blank" basemap requirement.

Run: pixi run python scripts/build_basemap_style.py
"""
import json
from pathlib import Path

import requests

SOURCE_STYLE_URL = "https://tiles.openfreemap.org/styles/liberty"
OUTPUT_PATH = Path(__file__).resolve().parent.parent / "frontend" / "src" / "basemapStyle.json"

KEEP_LAYERS = {
    "background",
    "park",
    "park_outline",
    "landuse_residential",
    "landcover_wood",
    "landcover_grass",
    "water",
    "waterway_river",
    "road_trunk_primary_casing",
    "road_trunk_primary",
    "road_motorway_casing",
    "road_motorway",
    "highway-shield-us-interstate",
    "boundary_2",  # state/country boundaries; boundary_3 (county) dropped as too granular
    "water_name_point_label",
    "label_state",
    "label_city",
    "label_city_capital",
    "label_country_1",
}


def main():
    style = requests.get(SOURCE_STYLE_URL, timeout=30).json()

    layers = [l for l in style["layers"] if l["id"] in KEEP_LAYERS]
    missing = KEEP_LAYERS - {l["id"] for l in layers}
    if missing:
        raise RuntimeError(
            f"Upstream style no longer has layer(s) {missing} -- "
            "OpenFreeMap changed 'liberty', update KEEP_LAYERS."
        )

    style["layers"] = layers
    style["sources"] = {k: v for k, v in style["sources"].items() if k == "openmaptiles"}

    OUTPUT_PATH.write_text(json.dumps(style, indent=2))
    print(f"Wrote {len(layers)} layers to {OUTPUT_PATH}")


if __name__ == "__main__":
    main()
