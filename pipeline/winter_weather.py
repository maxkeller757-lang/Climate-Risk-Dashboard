"""
Winter Weather category: Winter Storm + Ice Storm + Heavy Snow + Blizzard,
NCEI Storm Events Database, 2015-2024.

Unlike Severe Convective, these event types carry no point lat/lon in
NCEI's bulk data -- they're reported by NWS public forecast zone (CZ_TYPE
'Z'). So instead of the 15mi point-buffer method, this uses a % area
overlay against the real NWS zone polygons (see sources/nws_zones.py,
spatial.zone_overlay_score).

Run: pixi run python pipeline/winter_weather.py
"""
import geopandas as gpd

from config import ZCTA_GEOMETRIES_PATH
from scoring import percentile_rank, upsert_zip_scores, write_layer_geojson
from sources.ncei_storm_events import load_zone_events, severity_weight
from sources.nws_zones import load_zones
from spatial import zone_overlay_score

CATEGORY = "winter_weather"
COLOR = "#6EC6E8"
EVENT_TYPES = ["Winter Storm", "Ice Storm", "Heavy Snow", "Blizzard"]


def main():
    zcta = gpd.read_parquet(ZCTA_GEOMETRIES_PATH)
    zones = load_zones()

    print(f"Loading {EVENT_TYPES} events (zone-based)...")
    events = load_zone_events(EVENT_TYPES)
    events["weight"] = events.apply(severity_weight, axis=1)
    print(f"{len(events)} events loaded across {events['STATE_ZONE'].nunique()} zones")

    raw = zone_overlay_score(zcta, zones, events, zone_key_col="STATE_ZONE", weight_col="weight")
    scored = percentile_rank(raw, raw_col="severity_score")

    upsert_zip_scores(CATEGORY, scored, raw_col="severity_score")
    write_layer_geojson(CATEGORY, COLOR)
    print(f"{CATEGORY}: done")


if __name__ == "__main__":
    main()
