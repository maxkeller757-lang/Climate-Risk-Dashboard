"""
Seismic category: 80% zonal-mean PGA (2018 USGS National Seismic Hazard
Model, 2% probability of exceedance in 50 years) + 20% distance-decayed
volcanic threat (2018 USGS National Volcanic Threat Assessment centers,
see sources/volcanoes.py). Both are point-in-time model outputs, not event
histories -- no 2015-2024 windowing applies here (see project README).

The two components are percentile-ranked independently first, then
blended 80/20 -- PGA (g) and the volcano proximity score are in unrelated
units, so blending raw values would let whichever has the larger numeric
range silently dominate. The stored "raw" value for this category is
therefore itself a blended percentile, not a physical unit like the other
categories' raw columns.

Run: pixi run python pipeline/seismic.py
"""
import geopandas as gpd

from config import ZCTA_GEOMETRIES_PATH
from scoring import percentile_rank, upsert_zip_scores, write_layer_geojson
from sources.nshm_seismic import rasterize_pga
from sources.volcanoes import load_volcanoes
from spatial import distance_weighted_score, raster_zonal_mean

CATEGORY = "seismic"
COLOR = "#8B5E3C"
PGA_WEIGHT = 0.8
VOLCANO_WEIGHT = 0.2
VOLCANO_RADIUS_MILES = 50.0


def main():
    zcta = gpd.read_parquet(ZCTA_GEOMETRIES_PATH)

    print("Computing zonal-mean PGA...")
    pga_tif = rasterize_pga()
    pga = raster_zonal_mean(zcta, str(pga_tif))
    pga["mean"] = pga["mean"].fillna(0)
    pga_scored = percentile_rank(pga, raw_col="mean", score_col="pga_score")

    print("Computing volcanic threat proximity...")
    volcanoes = load_volcanoes()
    volcano_points = gpd.GeoDataFrame(
        volcanoes,
        geometry=gpd.points_from_xy(volcanoes["lon"], volcanoes["lat"]),
        crs="EPSG:4326",
    )
    volcano_raw = distance_weighted_score(
        zcta, volcano_points, weight_col="weight", radius_miles=VOLCANO_RADIUS_MILES
    )
    volcano_scored = percentile_rank(
        volcano_raw, raw_col="exposure_score", score_col="volcano_score"
    )

    combined = pga_scored.merge(volcano_scored[["zcta5", "volcano_score"]], on="zcta5")
    combined["blended"] = (
        PGA_WEIGHT * combined["pga_score"] + VOLCANO_WEIGHT * combined["volcano_score"]
    )

    scored = percentile_rank(combined, raw_col="blended")
    upsert_zip_scores(CATEGORY, scored, raw_col="blended")
    write_layer_geojson(CATEGORY, COLOR)
    print(f"{CATEGORY}: done")


if __name__ == "__main__":
    main()
