"""
Severe Convective category: Tornado + Hail + Thunderstorm Wind, NCEI Storm
Events Database, 2015-2024, 15mi buffer around ZCTA centroids.

NCEI Storm Events is a human-report database: report density tracks
population density as much as it tracks actual storm activity (a tornado
in a city gets seen and reported; the same tornado over open farmland may
not). Left uncorrected this makes every major metro look like a hazard
hotspot regardless of real climatology. See
scoring.population_bias_correct -- the raw severity score is detrended
against ZCTA population density (Census county population estimates,
areally apportioned onto ZCTAs) before percentile ranking.

Run: pixi run python pipeline/severe_convective.py
"""
import geopandas as gpd
import pandas as pd

from config import ZCTA_GEOMETRIES_PATH, EQUAL_AREA_CRS
from scoring import percentile_rank, population_bias_correct, upsert_zip_scores, write_layer_geojson
from sources.census_counties import load_counties
from sources.census_population import load_county_population
from sources.ncei_storm_events import load_events, severity_weight
from spatial import area_apportioned_sum, buffer_point_score

CATEGORY = "severe_convective"
COLOR = "#7B2D8E"
EVENT_TYPES = ["Tornado", "Hail", "Thunderstorm Wind"]


def main():
    zcta = gpd.read_parquet(ZCTA_GEOMETRIES_PATH)

    print(f"Loading {EVENT_TYPES} events...")
    events = load_events(EVENT_TYPES)
    events["weight"] = events.apply(severity_weight, axis=1)
    print(f"{len(events)} events loaded")

    raw = buffer_point_score(zcta, events, weight_col="weight", radius_miles=15.0)

    print("Apportioning county population onto ZCTAs for reporting-bias correction...")
    counties = load_counties()
    population = load_county_population()
    pop_by_zcta = area_apportioned_sum(zcta, counties, "GEOID", population)
    pop_by_zcta = pop_by_zcta.rename(columns={"value": "population"})

    area_km2 = pd.DataFrame(
        {"zcta5": zcta["zcta5"], "area_km2": zcta.to_crs(EQUAL_AREA_CRS).geometry.area / 1e6}
    )
    pop_by_zcta = pop_by_zcta.merge(area_km2, on="zcta5")
    pop_by_zcta["density"] = pop_by_zcta["population"] / pop_by_zcta["area_km2"].clip(lower=1e-6)

    raw = raw.merge(pop_by_zcta[["zcta5", "population", "density"]], on="zcta5", how="left")
    raw["density"] = raw["density"].fillna(0)

    corrected = population_bias_correct(raw, raw_col="severity_score", density_col="density")
    scored = percentile_rank(corrected, raw_col="bias_corrected")

    upsert_zip_scores(CATEGORY, scored, raw_col="severity_score")
    write_layer_geojson(CATEGORY, COLOR)
    print(f"{CATEGORY}: done")


if __name__ == "__main__":
    main()
