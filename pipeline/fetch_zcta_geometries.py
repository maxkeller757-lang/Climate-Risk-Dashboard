"""
Phase 0: download Census TIGER/Line 2023 ZCTA5 polygons, clip to CONUS, fix
into a gapless non-overlapping coverage, simplify for web rendering, and
write data/zcta_geometries.parquet.

Two issues in the raw TIGER data + a naive simplify this specifically
fixes:

1. Per-polygon simplification (geopandas' old .simplify()) is
   topology-unaware: adjacent ZCTAs' shared edges get simplified
   independently and drift apart, producing overlaps and sliver gaps at
   every shared boundary. Fixed with GeoSeries.simplify_coverage(), which
   simplifies the whole set as one topology so shared edges stay shared.
2. TIGER's ZCTA5 layer does not cover 100% of CONUS land -- some
   low-population/unincorporated land has no assigned ZCTA, which renders
   as a blank hole in the map. Fixed by computing the gap between the ZCTA
   union and a real land mask (dissolved Census county boundaries, which do
   fully tile CONUS land), then merging each gap piece into its nearest
   ZCTA by boundary distance.

Run: pixi run python pipeline/fetch_zcta_geometries.py
"""
import sys
import zipfile
from pathlib import Path

import geopandas as gpd
import pandas as pd
import requests
from shapely import make_valid

from config import (
    CENSUS_ZCTA_URL,
    COASTAL_CLOSING_BUFFER_M,
    CONUS_BBOX,
    COVERAGE_SIMPLIFY_TOLERANCE_M,
    EQUAL_AREA_CRS,
    MIN_GAP_AREA_M2,
    NO_ZIP_PREFIX,
    RAW_DIR,
    WEB_CRS,
    ZCTA_GEOMETRIES_PATH,
)

sys.path.insert(0, str(Path(__file__).resolve().parent / "sources"))
from census_counties import load_counties  # noqa: E402


def download_zcta_shapefile() -> Path:
    RAW_DIR.mkdir(parents=True, exist_ok=True)
    zip_path = RAW_DIR / "tl_2023_us_zcta520.zip"
    if zip_path.exists():
        print(f"Already downloaded: {zip_path}")
        return zip_path

    print(f"Downloading {CENSUS_ZCTA_URL} ...")
    with requests.get(CENSUS_ZCTA_URL, stream=True, timeout=300) as r:
        r.raise_for_status()
        with open(zip_path, "wb") as f:
            for chunk in r.iter_content(chunk_size=1 << 20):
                f.write(chunk)
    print(f"Saved {zip_path} ({zip_path.stat().st_size / 1e6:.1f} MB)")
    return zip_path


def _fill_gaps(zcta: gpd.GeoDataFrame) -> gpd.GeoDataFrame:
    """Find every piece of land with no assigned ZCTA and give it its own
    synthetic NOZIP-##### polygon (not merged into a neighboring real
    ZCTA -- that would misrepresent that ZCTA's actual delivery area).
    `zcta` must already be in EQUAL_AREA_CRS. Two gap sources, since
    neither alone covers everything:

    1. County-boundary gaps: land inside the dissolved Census county
       mask but outside the ZCTA union -- mostly inland low-population
       land TIGER never assigned a ZCTA to.
    2. Coastal-closing gaps: small gaps a morphological closing (buffer
       the ZCTA union out then back in) finds right at the coast --
       tidal marsh, barrier-island channels, etc. The county mask alone
       misses these because county cartographic boundaries are
       water-clipped along the coast the same way ZCTA5 is, so a plain
       land-mask diff sees no discrepancy there at all. The closing
       distance (config.COASTAL_CLOSING_BUFFER_M) only bridges gaps
       narrower than 2x itself, so genuinely open bays/sounds stay open.
    """
    print("Building CONUS land mask from Census county boundaries...")
    counties = load_counties().to_crs(EQUAL_AREA_CRS)
    land_mask = counties.union_all()

    zcta_union = zcta.union_all()
    county_gaps = land_mask.difference(zcta_union)

    print(f"Closing coastal gaps (buffer={COASTAL_CLOSING_BUFFER_M}m)...")
    closed = zcta_union.buffer(COASTAL_CLOSING_BUFFER_M).buffer(-COASTAL_CLOSING_BUFFER_M)
    coastal_gaps = closed.difference(zcta_union)

    all_gaps = county_gaps.union(coastal_gaps)
    gap_gdf = gpd.GeoDataFrame(geometry=[all_gaps], crs=EQUAL_AREA_CRS).explode(
        index_parts=False
    )
    gap_gdf = gap_gdf[gap_gdf.geometry.area >= MIN_GAP_AREA_M2].reset_index(drop=True)
    if len(gap_gdf) == 0:
        print("No coverage gaps found.")
        return zcta

    total_gap_area_km2 = gap_gdf.geometry.area.sum() / 1e6
    print(f"Found {len(gap_gdf)} gap piece(s) totaling {total_gap_area_km2:.1f} km^2 with no ZIP code.")

    gap_gdf["zcta5"] = [f"{NO_ZIP_PREFIX}{i:05d}" for i in range(1, len(gap_gdf) + 1)]

    return gpd.GeoDataFrame(
        pd.concat([zcta[["zcta5", "geometry"]], gap_gdf[["zcta5", "geometry"]]], ignore_index=True),
        crs=EQUAL_AREA_CRS,
    )


def main():
    zip_path = download_zcta_shapefile()

    extract_dir = RAW_DIR / "tl_2023_us_zcta520"
    if not extract_dir.exists():
        print("Extracting shapefile...")
        with zipfile.ZipFile(zip_path) as zf:
            zf.extractall(extract_dir)

    shp_files = list(extract_dir.glob("*.shp"))
    if not shp_files:
        raise FileNotFoundError(f"No .shp found in {extract_dir}")

    print("Reading shapefile into GeoDataFrame...")
    gdf = gpd.read_file(shp_files[0])

    zcta_col = "ZCTA5CE20" if "ZCTA5CE20" in gdf.columns else "ZCTA5CE10"
    gdf = gdf.rename(columns={zcta_col: "zcta5"})[["zcta5", "geometry"]]

    if gdf.crs is None or gdf.crs.to_string() != WEB_CRS:
        gdf = gdf.to_crs(WEB_CRS)

    print("Clipping to CONUS bounding box (drops AK/HI/PR/territories)...")
    minx, miny, maxx, maxy = CONUS_BBOX
    gdf = gdf.cx[minx:maxx, miny:maxy]

    gdf = gdf.to_crs(EQUAL_AREA_CRS)
    gdf["geometry"] = gdf["geometry"].apply(
        lambda g: make_valid(g) if g is not None and not g.is_valid else g
    )
    gdf = gdf[~gdf.geometry.is_empty & gdf.geometry.notna()].reset_index(drop=True)

    print(f"Simplifying {len(gdf)} polygons as one coverage (tolerance={COVERAGE_SIMPLIFY_TOLERANCE_M}m)...")
    gdf["geometry"] = gdf.geometry.simplify_coverage(
        COVERAGE_SIMPLIFY_TOLERANCE_M, simplify_boundary=True
    )

    gdf = _fill_gaps(gdf)

    gdf = gdf.to_crs(WEB_CRS)

    # Repair, don't discard. simplify_coverage can leave a polygon
    # self-intersecting, and silently filtering those out deletes real
    # ZCTAs and punches a hole in the map -- it cost us 31027 and 30454
    # (two adjacent rural Georgia ZCTAs, 516 km^2 between them), which
    # also made those ZIPs un-searchable in the API.
    broken = ~gdf.geometry.is_valid
    if broken.any():
        print(f"Repairing {broken.sum()} invalid geometry/geometries after simplification...")
        gdf.loc[broken, "geometry"] = gdf.loc[broken, "geometry"].apply(make_valid)

    dropped = gdf[gdf.geometry.is_empty | gdf.geometry.isna() | ~gdf.geometry.is_valid]
    if len(dropped):
        raise RuntimeError(
            f"{len(dropped)} polygon(s) are still unusable after repair "
            f"(e.g. {dropped['zcta5'].head(5).tolist()}). Dropping them would "
            "leave holes in CONUS -- fix the geometry instead."
        )
    gdf = gdf.reset_index(drop=True)

    ZCTA_GEOMETRIES_PATH.parent.mkdir(parents=True, exist_ok=True)
    gdf.to_parquet(ZCTA_GEOMETRIES_PATH)
    print(f"Wrote {len(gdf)} ZCTA polygons to {ZCTA_GEOMETRIES_PATH}")


if __name__ == "__main__":
    main()
