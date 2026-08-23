"""
USGS National Seismic Hazard Model (2018 update), PGA at 2% probability of
exceedance in 50 years, site class B/C (firm rock reference). This is a
point-in-time hazard model, not an event history -- no 2015-2024 windowing
applies (see the project README).

Published as a 0.05deg grid of points (lon, lat, PGA, SA0.2, SA1.0, SA5.0),
not a raster -- rasterized here on load so it can go through the same
zonal-stats path as Wildfire's WHP raster.

Source: https://www.sciencebase.gov/catalog/item/5d5597d0e4b01d82ce8e3ff1
"""
from pathlib import Path

import numpy as np
import rasterio
import requests
from rasterio.transform import from_origin

from config import RAW_DIR, WEB_CRS

CSV_URL = (
    "https://www.sciencebase.gov/catalog/file/get/5d5597d0e4b01d82ce8e3ff1"
    "?f=__disk__e2%2Fa2%2F02%2Fe2a202a984d3c7c19e4de16cbd8d662baf113898"
)
GRID_SPACING_DEG = 0.05


def download_pga_grid() -> Path:
    path = RAW_DIR / "nshm_2018_pga.csv"
    if not path.exists():
        RAW_DIR.mkdir(parents=True, exist_ok=True)
        print(f"Downloading {CSV_URL} ...")
        resp = requests.get(CSV_URL, timeout=120)
        resp.raise_for_status()
        path.write_bytes(resp.content)
    return path


def rasterize_pga() -> Path:
    """Turns the point grid CSV into a GeoTIFF so it can be zonal-stat'd
    the same way as any other raster category. Cached -- only rebuilt if
    missing."""
    out_path = RAW_DIR / "nshm_2018_pga.tif"
    if out_path.exists():
        return out_path

    csv_path = download_pga_grid()
    data = np.loadtxt(csv_path, delimiter=",", usecols=(0, 1, 2))
    lon, lat, pga = data[:, 0], data[:, 1], data[:, 2]

    lon_vals = np.round(lon / GRID_SPACING_DEG).astype(int)
    lat_vals = np.round(lat / GRID_SPACING_DEG).astype(int)
    lon_min, lon_max = lon_vals.min(), lon_vals.max()
    lat_min, lat_max = lat_vals.min(), lat_vals.max()

    width = lon_max - lon_min + 1
    height = lat_max - lat_min + 1
    grid = np.full((height, width), np.nan, dtype="float32")
    row = lat_max - lat_vals  # north-up raster: row 0 = max lat
    col = lon_vals - lon_min
    grid[row, col] = pga

    transform = from_origin(
        lon_min * GRID_SPACING_DEG - GRID_SPACING_DEG / 2,
        lat_max * GRID_SPACING_DEG + GRID_SPACING_DEG / 2,
        GRID_SPACING_DEG,
        GRID_SPACING_DEG,
    )
    with rasterio.open(
        out_path, "w", driver="GTiff", height=height, width=width, count=1,
        dtype="float32", crs=WEB_CRS, transform=transform, nodata=np.nan,
    ) as dst:
        dst.write(grid, 1)

    print(f"Rasterized PGA grid to {out_path} ({width}x{height})")
    return out_path
