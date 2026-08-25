"""
Winter Weather category: Winter Storm + Ice Storm + Heavy Snow + Blizzard,
NCEI Storm Events Database, 2015-2024.

Unlike Severe Convective, these event types carry no point lat/lon in
NCEI's bulk data -- they're reported by NWS public forecast zone (CZ_TYPE
'Z'). So instead of the 15mi point-buffer method, this uses a % area
overlay against the real NWS zone polygons (see sources/nws_zones.py,
spatial.zone_overlay_score).

Zone granularity note: NWS zones never cross state lines, and this raw
metric is heavily zero-inflated (20% of ZCTAs report zero events over 10
years) -- so percentile_rank() is very sensitive right at that mass of
zeros, and a single zone-boundary difference can swing a score 60+ points
(e.g. Jackson County CO's "below 9000ft" zone has a genuine 0-event count
-- its real winter severity gets tagged to the neighbouring "above 9000ft"
zone). Verified this isn't a join-key mismatch or an unnormalized-sum bug,
and that population/reporting-density correction (tried first, since it's
the same NCEI source Severe Convective corrects for) doesn't meaningfully
help here -- it's sparse zone-level counts, not reporting bias. Smoothed
with neighbours before ranking instead; see scoring.spatial_smooth.

Run: pixi run python pipeline/winter_weather.py
"""
import geopandas as gpd

from config import ZCTA_GEOMETRIES_PATH
from scoring import percentile_rank, spatial_smooth, upsert_zip_scores, write_layer_geojson
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

    print("Smoothing with neighbouring ZCTAs to soften zone-boundary cliffs...")
    smoothed = spatial_smooth(zcta, raw, raw_col="severity_score")
    scored = percentile_rank(smoothed, raw_col="spatially_smoothed")

    upsert_zip_scores(CATEGORY, scored, raw_col="severity_score")
    write_layer_geojson(CATEGORY, COLOR)
    print(f"{CATEGORY}: done")


if __name__ == "__main__":
    main()
