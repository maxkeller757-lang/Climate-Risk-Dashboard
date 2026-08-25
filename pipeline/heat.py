"""
Extreme Heat category: blend of (a) 60% avg days/year with max temp >90F
and (b) 40% avg days/year with NWS heat index >100F, 2015-2024, from
gridMET daily max temp + min relative humidity (see sources/gridmet.py,
sources/heat_index.py).

Both sub-metrics are already the same unit (days/year), so they're
blended directly as raw values -- unlike Wildfire/Seismic, there's no
percentile-pre-ranking needed to make the two components comparable.

Processes one gridMET-year at a time (each year's daily cube is ~1GB in
memory) and immediately reduces it to a small annual day-count grid before
moving to the next year, rather than holding all 10 years of daily data at
once.

Run: pixi run python pipeline/heat.py
"""
import geopandas as gpd
import netCDF4
import numpy as np
import rasterio
from rasterio.transform import from_origin

from config import END_YEAR, RAW_DIR, START_YEAR, WEB_CRS, ZCTA_GEOMETRIES_PATH
from scoring import percentile_rank, upsert_zip_scores, write_layer_geojson
from sources.gridmet import download_year, kelvin_to_fahrenheit
from sources.heat_index import rothfusz_heat_index
from spatial import raster_zonal_mean

CATEGORY = "heat"
COLOR = "#E85D04"
TEMP_THRESHOLD_F = 90.0
HEAT_INDEX_THRESHOLD_F = 100.0
TEMP_WEIGHT = 0.6
HEAT_INDEX_WEIGHT = 0.4


def _data_var(ds: netCDF4.Dataset) -> str:
    coords = {"day", "lat", "lon", "crs"}
    for name in ds.variables:
        if name not in coords:
            return name
    raise KeyError("No data variable found in gridMET file")


def _accumulate_year(year: int, temp_days_sum, hi_days_sum, grid_info):
    tmmx_path = download_year("tmmx", year)
    rmin_path = download_year("rmin", year)

    with netCDF4.Dataset(tmmx_path) as tmmx_ds, netCDF4.Dataset(rmin_path) as rmin_ds:
        tmax_var, rmin_var = _data_var(tmmx_ds), _data_var(rmin_ds)
        if grid_info["lat"] is None:
            grid_info["lat"] = tmmx_ds["lat"][:]
            grid_info["lon"] = tmmx_ds["lon"][:]

        n_days = tmmx_ds[tmax_var].shape[0]
        if temp_days_sum is None:
            shape = tmmx_ds[tmax_var].shape[1:]
            temp_days_sum = np.zeros(shape, dtype="float64")
            hi_days_sum = np.zeros(shape, dtype="float64")

        # Day-by-day, not the whole year at once: each day's slice is
        # ~3MB: (585, 1386) float32; the whole year would be ~1GB.
        for day in range(n_days):
            tmax_f = kelvin_to_fahrenheit(np.array(tmmx_ds[tmax_var][day, :, :]))
            rmin_pct = np.array(rmin_ds[rmin_var][day, :, :])
            temp_days_sum += tmax_f > TEMP_THRESHOLD_F

            hi = rothfusz_heat_index(tmax_f, rmin_pct)
            hi_days_sum += hi > HEAT_INDEX_THRESHOLD_F

    return temp_days_sum, hi_days_sum


def _write_raster(path, data, lat, lon):
    lat_desc = lat[0] > lat[-1]
    if not lat_desc:
        data = data[::-1, :]
        lat = lat[::-1]
    res_lat = abs(lat[1] - lat[0])
    res_lon = abs(lon[1] - lon[0])
    transform = from_origin(lon[0] - res_lon / 2, lat[0] + res_lat / 2, res_lon, res_lat)
    with rasterio.open(
        path, "w", driver="GTiff", height=data.shape[0], width=data.shape[1],
        count=1, dtype="float32", crs=WEB_CRS, transform=transform,
    ) as dst:
        dst.write(data.astype("float32"), 1)


def main():
    zcta = gpd.read_parquet(ZCTA_GEOMETRIES_PATH)

    # These two rasters are a pure function of the gridMET files, the
    # thresholds and the year range -- nothing about ZCTA geometry enters
    # into them. Only the zonal-stats step below depends on the polygons.
    # So a geometry change should not force a rebuild: re-deriving them
    # means a day-by-day pass over ~7,300 netCDF slices, which on a
    # machine short of free RAM and disk becomes I/O-bound and can run for
    # many hours. Every parameter that affects the contents is encoded in
    # the filename, so changing a threshold or the window invalidates the
    # cache automatically instead of silently reusing stale rasters.
    stem = f"{START_YEAR}_{END_YEAR}"
    temp_path = RAW_DIR / f"heat_days_over_{TEMP_THRESHOLD_F:.0f}f_{stem}.tif"
    hi_path = RAW_DIR / f"heat_index_days_over_{HEAT_INDEX_THRESHOLD_F:.0f}f_{stem}.tif"

    if temp_path.exists() and hi_path.exists():
        print(f"Reusing cached heat rasters ({temp_path.name}, {hi_path.name})")
    else:
        temp_sum, hi_sum = None, None
        grid_info = {"lat": None, "lon": None}
        for year in range(START_YEAR, END_YEAR + 1):
            print(f"Processing gridMET {year}...")
            temp_sum, hi_sum = _accumulate_year(year, temp_sum, hi_sum, grid_info)

        n_years = END_YEAR - START_YEAR + 1
        _write_raster(temp_path, temp_sum / n_years, grid_info["lat"], grid_info["lon"])
        _write_raster(hi_path, hi_sum / n_years, grid_info["lat"], grid_info["lon"])

    print("Computing zonal means...")
    temp_zonal = raster_zonal_mean(zcta, str(temp_path)).rename(columns={"mean": "avg_days_90f"})
    hi_zonal = raster_zonal_mean(zcta, str(hi_path)).rename(columns={"mean": "avg_days_hi100f"})

    combined = temp_zonal.merge(hi_zonal, on="zcta5")
    combined["avg_days_90f"] = combined["avg_days_90f"].fillna(0)
    combined["avg_days_hi100f"] = combined["avg_days_hi100f"].fillna(0)
    combined["blended_days"] = (
        TEMP_WEIGHT * combined["avg_days_90f"] + HEAT_INDEX_WEIGHT * combined["avg_days_hi100f"]
    )

    scored = percentile_rank(combined, raw_col="blended_days")
    upsert_zip_scores(CATEGORY, scored, raw_col="blended_days")
    write_layer_geojson(CATEGORY, COLOR)
    print(f"{CATEGORY}: done")


if __name__ == "__main__":
    main()
