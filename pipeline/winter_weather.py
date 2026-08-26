"""
Winter Weather category: average days per year with measurable winter
precipitation, 2015-2024, from gridMET daily precipitation + max temp
(see sources/gridmet.py).

Previously this category used NCEI Storm Events (Winter Storm/Ice
Storm/Heavy Snow/Blizzard), apportioned onto ZCTAs by area-overlap against
NWS forecast zone polygons. That was abandoned, not patched: NCEI Storm
Events is a human-report database, and report density tracks population,
observer-network coverage, and each NWS forecast office's own reporting
culture as much as it tracks actual winter weather. Two symptoms of that,
reported directly by a user: score clustering around Dallas (an urban
reporting-density artifact, nothing to do with Dallas actually getting
more winter weather than its surroundings), and sharp discontinuities at
state lines, particularly in Nevada (NWS zones never cross a state line,
so a difference in two states' reporting culture shows up as a hard edge
exactly on the border). A spatial-smoothing pass was tried first (see git
history) and reduced the *symptom*, but the raw signal itself was never a
measure of risk to begin with -- no amount of smoothing fixes that.

gridMET is model+station-blended physical measurement: zero human
reporting involved, so both symptoms disappear at the root. It's also a
continuous ~4km grid, not zone polygons, so there is no zone boundary for
a state-line artifact to form on in the first place -- unlike Air
Quality's county-line cliffs (a real granularity artifact in an otherwise
continuous value), this category no longer needs spatial_smooth at all.

A day counts as "winter precipitation" when it has at least 0.01in
liquid-equivalent precipitation (0.254mm -- the standard NWS threshold for
"measurable precipitation", not an arbitrary cutoff) AND a max temperature
at or below 32F. Max temp, not min: min temp is below freezing almost
every winter night everywhere, which barely discriminates one place from
another; max temp at or below freezing means the day never warmed above
freezing at all, a real and geographically differentiated signal.

This measures winter precipitation *frequency*, not snowfall *amount* --
SNODAS (NOAA/NOHRSC, gridded snow depth/SWE) would be the more direct
measurement, but ships as flat binary grids over FTP with no netCDF/
shapefile/CSV option, needing new ingestion code this project doesn't
otherwise have a pattern for. gridMET reuses the exact ingestion path
Heat already proved out, at the cost of measuring occurrence rather than
depth. Worth revisiting if snowfall amount specifically is ever needed.

Processes one gridMET-year at a time (each year's daily cube is ~1GB in
memory) and immediately reduces it to a small annual day-count grid before
moving to the next year, rather than holding all 10 years of daily data at
once -- same approach as heat.py.

Run: pixi run python pipeline/winter_weather.py
"""
import geopandas as gpd
import netCDF4
import numpy as np
import rasterio
from rasterio.transform import from_origin

from config import END_YEAR, RAW_DIR, START_YEAR, WEB_CRS, ZCTA_GEOMETRIES_PATH
from scoring import percentile_rank, upsert_zip_scores, write_layer_geojson
from sources.gridmet import download_year, kelvin_to_fahrenheit
from spatial import raster_zonal_mean

CATEGORY = "winter_weather"
COLOR = "#6EC6E8"
PRECIP_THRESHOLD_MM = 0.254  # 0.01in -- NWS's own "measurable precipitation" cutoff
TEMP_THRESHOLD_F = 32.0


def _data_var(ds: netCDF4.Dataset) -> str:
    coords = {"day", "lat", "lon", "crs"}
    for name in ds.variables:
        if name not in coords:
            return name
    raise KeyError("No data variable found in gridMET file")


def _accumulate_year(year: int, day_sum, grid_info):
    pr_path = download_year("pr", year)
    tmmx_path = download_year("tmmx", year)

    with netCDF4.Dataset(pr_path) as pr_ds, netCDF4.Dataset(tmmx_path) as tmmx_ds:
        pr_var, tmax_var = _data_var(pr_ds), _data_var(tmmx_ds)
        if grid_info["lat"] is None:
            grid_info["lat"] = pr_ds["lat"][:]
            grid_info["lon"] = pr_ds["lon"][:]

        n_days = pr_ds[pr_var].shape[0]
        if day_sum is None:
            day_sum = np.zeros(pr_ds[pr_var].shape[1:], dtype="float64")

        # Day-by-day, not the whole year at once -- same reasoning as
        # heat.py: a full year in memory at once is ~1GB per variable.
        for day in range(n_days):
            # NOT np.array(var[day,:,:]): gridMET packs these as scaled
            # uint16 with a _FillValue for the ~40% of this WGS84 grid
            # that's ocean/Canada/Mexico, outside CONUS. Indexing the
            # Variable returns a properly-scaled MaskedArray, but
            # wrapping that in np.array() discards the mask and returns
            # the *raw, unscaled* fill sentinel (32767, i.e. 3276.7mm of
            # "precipitation") for every masked cell -- confirmed
            # directly against this exact file. Comparing masked booleans
            # and filling False only at the end keeps every masked cell
            # correctly excluded regardless of which variable it came
            # from, rather than reasoning about two different per-variable
            # fill values.
            precip_mm = pr_ds[pr_var][day, :, :]
            tmax_f = kelvin_to_fahrenheit(tmmx_ds[tmax_var][day, :, :])
            day_flag = (precip_mm >= PRECIP_THRESHOLD_MM) & (tmax_f <= TEMP_THRESHOLD_F)
            day_sum += np.ma.filled(day_flag, False)

    return day_sum


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

    # Pure function of the gridMET files, the thresholds, and the year
    # range -- not of ZCTA geometry -- so a geometry change shouldn't force
    # a rebuild of this. Every parameter that affects the contents is
    # encoded in the filename, so changing a threshold or the window
    # invalidates the cache automatically instead of silently reusing a
    # stale raster (see heat.py, which established this pattern after a
    # 26-hour stall from re-deriving a raster that hadn't actually changed).
    stem = f"{START_YEAR}_{END_YEAR}"
    raster_path = (
        RAW_DIR
        / f"winter_precip_days_{PRECIP_THRESHOLD_MM:.3f}mm_{TEMP_THRESHOLD_F:.0f}f_{stem}.tif"
    )

    if raster_path.exists():
        print(f"Reusing cached winter precipitation raster ({raster_path.name})")
    else:
        day_sum = None
        grid_info = {"lat": None, "lon": None}
        for year in range(START_YEAR, END_YEAR + 1):
            print(f"Processing gridMET {year}...")
            day_sum = _accumulate_year(year, day_sum, grid_info)

        n_years = END_YEAR - START_YEAR + 1
        _write_raster(raster_path, day_sum / n_years, grid_info["lat"], grid_info["lon"])

    print("Computing zonal means...")
    zonal = raster_zonal_mean(zcta, str(raster_path)).rename(
        columns={"mean": "avg_winter_precip_days"}
    )
    zonal["avg_winter_precip_days"] = zonal["avg_winter_precip_days"].fillna(0)

    scored = percentile_rank(zonal, raw_col="avg_winter_precip_days")
    upsert_zip_scores(CATEGORY, scored, raw_col="avg_winter_precip_days")
    write_layer_geojson(CATEGORY, COLOR)
    print(f"{CATEGORY}: done")


if __name__ == "__main__":
    main()
