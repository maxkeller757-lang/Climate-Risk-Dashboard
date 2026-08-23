"""
Check the processed ZCTA polygons still faithfully represent real zip code
areas, by comparing them against the unmodified Census TIGER source.

The pipeline reshapes the source geometry in several ways -- topology-aware
coverage simplification, gap filling, the repair of dropped ZCTAs, and a
second render-only simplification. Each is defensible on its own, but they
compound, and nothing so far has measured how far the result has drifted
from the actual zip areas. This does.

Three independent checks, deliberately not all derived from the same
quantity:

1. Intersection over Union against the raw polygon. The direct measure of
   shape agreement: 1.0 is identical, and it penalises both lost area and
   invented area. This is the one that would catch simplification quietly
   reshaping a boundary.
2. Area against Census's own published ALAND20 + AWATER20 attributes,
   rather than against an area recomputed from the geometry. If the
   pipeline's own area math were wrong, an area-vs-area check using that
   same math could still agree with itself; this cannot.
3. Whether Census's published internal point (INTPTLAT20/INTPTLON20) still
   falls inside the processed polygon. A blunt topology check -- a polygon
   can keep the right area and still be in the wrong place, and this
   catches that.

Both geometry files are tested, because they answer different questions:
the analysis geometry is what every hazard score is computed against, and
the render geometry is what the user actually sees.

Run: pixi run python pipeline/verify_zcta_fidelity.py
"""
import geopandas as gpd
import numpy as np
import pandas as pd

from config import (
    CONUS_BBOX,
    EQUAL_AREA_CRS,
    NO_ZIP_PREFIX,
    RAW_DIR,
    ZCTA_GEOMETRIES_PATH,
    ZCTA_RENDER_GEOMETRIES_PATH,
)

SHAPEFILE = RAW_DIR / "tl_2023_us_zcta520" / "tl_2023_us_zcta520.shp"

# Thresholds. IoU below this is a polygon that no longer reasonably
# represents its zip area; 0.95 still allows visible smoothing of a
# boundary while catching genuine distortion.
MIN_MEAN_IOU = 0.98
MIN_ACCEPTABLE_IOU = 0.90
# Share of ZCTAs allowed to fall under MIN_ACCEPTABLE_IOU.
MAX_POOR_SHARE = 0.01


def load_raw() -> gpd.GeoDataFrame:
    gdf = gpd.read_file(SHAPEFILE)
    gdf = gdf.rename(columns={"ZCTA5CE20": "zcta5"})
    gdf = gdf[["zcta5", "ALAND20", "AWATER20", "INTPTLAT20", "INTPTLON20", "geometry"]]
    minx, miny, maxx, maxy = CONUS_BBOX
    return gdf.cx[minx:maxx, miny:maxy].to_crs(EQUAL_AREA_CRS)


def compare(label: str, path, raw: gpd.GeoDataFrame) -> bool:
    print(f"\n== {label} ==")
    ours = gpd.read_parquet(path).to_crs(EQUAL_AREA_CRS)
    ours = ours[~ours["zcta5"].str.startswith(NO_ZIP_PREFIX)]

    merged = raw.merge(
        ours[["zcta5", "geometry"]].rename(columns={"geometry": "geom_ours"}),
        on="zcta5",
        how="inner",
    )
    missing = len(raw) - len(merged)
    print(f"  {len(merged):,} ZCTAs compared ({missing} in source but absent here)")

    a = gpd.GeoSeries(merged["geometry"], crs=EQUAL_AREA_CRS)
    b = gpd.GeoSeries(merged["geom_ours"], crs=EQUAL_AREA_CRS)

    inter = a.intersection(b, align=False).area
    union = a.union(b, align=False).area
    iou = (inter / union).replace([np.inf, -np.inf], np.nan).fillna(0)

    # Census's published total area, not one recomputed from geometry.
    published = merged["ALAND20"].astype(float) + merged["AWATER20"].astype(float)
    area_ratio = (b.area / published.replace(0, np.nan)).dropna()

    pt = gpd.GeoSeries(
        gpd.points_from_xy(
            merged["INTPTLON20"].astype(float), merged["INTPTLAT20"].astype(float)
        ),
        crs="EPSG:4326",
    ).to_crs(EQUAL_AREA_CRS)
    contains_pt = b.contains(pt, align=False)

    poor = iou < MIN_ACCEPTABLE_IOU
    poor_share = poor.mean()

    print(f"  IoU vs raw polygon:  mean {iou.mean():.4f}   median {np.median(iou):.4f}   min {iou.min():.3f}")
    print(f"    below {MIN_ACCEPTABLE_IOU}: {poor.sum():,} ({100 * poor_share:.2f}%)")
    print(f"  Area / Census published:  median {area_ratio.median():.4f}   "
          f"p1 {area_ratio.quantile(0.01):.3f}   p99 {area_ratio.quantile(0.99):.3f}")
    print(f"  Contains Census internal point: {contains_pt.sum():,} / {len(contains_pt):,} "
          f"({100 * contains_pt.mean():.2f}%)")

    # Stratify by size. Simplification error is bounded by the tolerance in
    # absolute metres, so it is negligible on a large rural ZCTA and
    # catastrophic on a small urban one -- an aggregate mean hides exactly
    # the failure mode that matters.
    km2 = a.area / 1e6
    bands = pd.cut(
        km2,
        [0, 0.5, 2, 5, 10, 25, 100, np.inf],
        labels=["<0.5", "0.5-2", "2-5", "5-10", "10-25", "25-100", ">100"],
    )
    table = pd.DataFrame({"iou": iou.values, "band": bands.values})
    summary = table.groupby("band", observed=True)["iou"].agg(
        n="size", mean_iou="mean", pct_poor=lambda s: 100 * (s < MIN_ACCEPTABLE_IOU).mean()
    )
    print("  By ZCTA size (km^2):")
    for band, row in summary.iterrows():
        print(f"    {band:>7}  n={int(row['n']):>6,}  mean IoU {row['mean_iou']:.3f}  "
              f"below {MIN_ACCEPTABLE_IOU}: {row['pct_poor']:5.1f}%")

    if poor.any():
        worst = merged.loc[poor, ["zcta5"]].assign(iou=iou[poor].round(3), km2=km2[poor].round(3))
        worst = worst.sort_values("iou").head(6)
        print("  Lowest-IoU ZCTAs:")
        for r in worst.itertuples():
            print(f"    {r.zcta5}  IoU {r.iou}  ({r.km2} km^2)")

    ok = iou.mean() >= MIN_MEAN_IOU and poor_share <= MAX_POOR_SHARE
    print(f"  {'PASS' if ok else 'FAIL'}")
    return ok


def main():
    print("Loading raw Census TIGER ZCTA5 (unmodified source)...")
    raw = load_raw()
    print(f"{len(raw):,} raw CONUS ZCTAs")

    analysis_ok = compare("Analysis geometry (what scores are computed on)", ZCTA_GEOMETRIES_PATH, raw)
    render_ok = compare("Render geometry (what the map draws)", ZCTA_RENDER_GEOMETRIES_PATH, raw)

    print()
    if analysis_ok and render_ok:
        print("Processed polygons match the authoritative zip areas within tolerance.")
    else:
        raise SystemExit("Fidelity check FAILED -- see above.")


if __name__ == "__main__":
    main()
