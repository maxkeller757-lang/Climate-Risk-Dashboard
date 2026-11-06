"""
Hurricane / Tropical category: zonal-mean 50-year-return-period tropical
cyclone wind speed from the STORM synthetic-track dataset (sources/
storm_wind.py), percentile-ranked.

History, since this category has been rebuilt twice: (1) NOAA HURDAT2
track-centroid proximity needed two hand-tuned corrections (contrast
stretch, coast-distance divisor) just to look plausible. (2) FEMA NRI's
loss rate (HRCN_ALRB) bakes in regional building age/value, ranking the
Northeast too high, and its Connecticut tract IDs use 2022+ Planning
Regions that don't match this project's tract vintage, so all of CT
silently scored zero. This raster approach has neither problem: it is a
pure wind-speed hazard and involves no tract join.

50 years, not a longer design-basis return period: every other category
reflects recent, tangible experience, and 50 years is roughly "within a
homeowner's lifetime". Change storm_wind.RETURN_PERIOD_YEARS to revisit.

Like Seismic's PGA, this is a point-in-time model output, not a 2015-2024
event history. Zero-wind pixels (inland) are real zeros, so no NaN
handling beyond a ZCTA falling outside the raster entirely.

Run: pixi run python pipeline/hurricane.py
"""
import geopandas as gpd

from config import ZCTA_GEOMETRIES_PATH
from scoring import percentile_rank, upsert_zip_scores, write_layer_geojson
from sources.storm_wind import download_wind_speed_raster
from spatial import raster_zonal_mean

CATEGORY = "hurricane"
COLOR = "#00707A"


def main():
    zcta = gpd.read_parquet(ZCTA_GEOMETRIES_PATH)

    print("Computing zonal-mean STORM wind speed...")
    raw = raster_zonal_mean(zcta, str(download_wind_speed_raster()))
    raw = raw.rename(columns={"mean": "wind_speed_ms"})
    raw["wind_speed_ms"] = raw["wind_speed_ms"].fillna(0.0)

    scored = percentile_rank(raw, raw_col="wind_speed_ms")
    upsert_zip_scores(CATEGORY, scored, raw_col="wind_speed_ms")
    write_layer_geojson(CATEGORY, COLOR)
    print(f"{CATEGORY}: done")


if __name__ == "__main__":
    main()
