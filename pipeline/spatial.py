"""Reusable spatial-join helpers shared across category ingestion modules."""
import geopandas as gpd
import pandas as pd
import rasterio

from config import EQUAL_AREA_CRS

MILES_TO_METERS = 1609.34


def raster_zonal_mean(zcta_gdf: gpd.GeoDataFrame, raster_path: str) -> pd.DataFrame:
    """Mean raster value within each ZCTA polygon (rasterstats, windowed
    per-polygon reads -- doesn't load the whole raster into memory). Used
    by Wildfire (WHP) and Seismic (PGA), both point-in-time model rasters.
    Reprojects ZCTAs to the raster's own CRS first -- rasterstats does not
    reproject for you, and silently gives wrong numbers on a CRS mismatch
    rather than erroring.

    Returns [zcta5, mean] (mean is NaN, not 0, where the raster has no
    valid data under a ZCTA -- e.g. WHP excludes water/non-burnable land,
    which isn't the same as "zero hazard").
    """
    import rasterstats

    with rasterio.open(raster_path) as src:
        raster_crs = src.crs

    zcta_proj = zcta_gdf.to_crs(raster_crs)
    # all_touched=True: rasterstats' default only counts a pixel if its
    # *center* falls inside the polygon, which silently returns "no data"
    # (None, not 0) for any ZCTA smaller than one raster cell -- common for
    # dense urban ZCTAs against a coarse raster like the 0.05deg PGA grid.
    stats = rasterstats.zonal_stats(
        zcta_proj.geometry, raster_path, stats=["mean"], nodata=None,
        all_touched=True, geojson_out=False,
    )
    return pd.DataFrame({"zcta5": zcta_proj["zcta5"].values, "mean": [s["mean"] for s in stats]})


def intersect_count(zcta_gdf: gpd.GeoDataFrame, features_gdf: gpd.GeoDataFrame) -> pd.DataFrame:
    """Count of features_gdf polygons intersecting each ZCTA (not
    area-weighted -- a ZCTA touched by a burn perimeter at all counts it
    once). Used by Wildfire's MTBS historical-burn-count component.

    Returns [zcta5, count], one row per ZCTA (0 where none intersect).
    """
    joined = gpd.sjoin(
        zcta_gdf[["zcta5", "geometry"]], features_gdf[["geometry"]], predicate="intersects"
    )
    counts = joined.groupby("zcta5").size().reset_index(name="count")
    all_zctas = zcta_gdf[["zcta5"]].drop_duplicates()
    result = all_zctas.merge(counts, on="zcta5", how="left")
    result["count"] = result["count"].fillna(0)
    return result


def coast_distance_miles(zcta_gdf: gpd.GeoDataFrame) -> pd.DataFrame:
    """Distance from each ZCTA centroid to the nearest edge of the CONUS
    land mask (dissolved Census county boundaries -- no new data pulled,
    reuses the same source as the ZCTA gap-fill step). In practice this is
    overwhelmingly a true coastline distance: the land mask's edge also
    includes the Canada/Mexico land border, but ZCTAs near that border and
    far from any real hurricane track already have ~zero raw exposure, so
    treating that border as "coast" there doesn't inflate anything -- a
    near-zero score divided by anything is still near zero. Used by
    Hurricane's coastal concentration.

    Returns [zcta5, coast_distance_miles].
    """
    from sources.census_counties import load_counties

    land_boundary = load_counties().to_crs(EQUAL_AREA_CRS).union_all().boundary
    centroids = zcta_centroids(zcta_gdf)
    distance_m = centroids.geometry.distance(land_boundary)
    return pd.DataFrame(
        {"zcta5": centroids["zcta5"], "coast_distance_miles": distance_m / MILES_TO_METERS}
    )


def zcta_centroids(zcta_gdf: gpd.GeoDataFrame) -> gpd.GeoDataFrame:
    """Centroid of each ZCTA polygon, computed in an equal-area CRS so the
    centroid position and any subsequent buffering are metrically accurate."""
    projected = zcta_gdf.to_crs(EQUAL_AREA_CRS)
    centroids = projected.copy()
    centroids["geometry"] = projected.geometry.centroid
    return centroids


def buffer_point_score(
    zcta_gdf: gpd.GeoDataFrame,
    events_gdf: gpd.GeoDataFrame,
    weight_col: str,
    radius_miles: float = 15.0,
) -> pd.DataFrame:
    """For each ZCTA, count events and sum `weight_col` over all events
    within `radius_miles` of the ZCTA centroid.

    Used by Severe Convective and Winter Weather (both: NCEI Storm Events
    point data, 15mi buffer). Returns [zcta5, event_count, severity_score],
    with a row (score 0) for every ZCTA even if no events fell in range, so
    downstream percentile ranking isn't skewed by missing rows.
    """
    centroids = zcta_centroids(zcta_gdf)
    centroids = centroids.copy()
    centroids["geometry"] = centroids.geometry.buffer(radius_miles * MILES_TO_METERS)

    events_proj = events_gdf.to_crs(EQUAL_AREA_CRS)

    joined = gpd.sjoin(
        events_proj[["geometry", weight_col]],
        centroids[["zcta5", "geometry"]],
        how="inner",
        predicate="within",
    )

    agg = (
        joined.groupby("zcta5")
        .agg(event_count=(weight_col, "size"), severity_score=(weight_col, "sum"))
        .reset_index()
    )

    all_zctas = zcta_gdf[["zcta5"]].drop_duplicates()
    result = all_zctas.merge(agg, on="zcta5", how="left")
    result[["event_count", "severity_score"]] = result[
        ["event_count", "severity_score"]
    ].fillna(0)
    return result


def distance_weighted_score(
    zcta_gdf: gpd.GeoDataFrame,
    points_gdf: gpd.GeoDataFrame,
    weight_col: str,
    radius_miles: float,
) -> pd.DataFrame:
    """For each ZCTA, sum weight_col * (1 - distance/radius_miles) over all
    points within radius_miles of the ZCTA centroid -- a linear-decay
    proximity weighting, vs. buffer_point_score's flat in-or-out count.
    Used by Hurricane (HURDAT2 track points, wind-speed weighted).

    Returns [zcta5, exposure_score], one row per ZCTA (0 if none in range).
    """
    centroids = zcta_centroids(zcta_gdf)
    radius_m = radius_miles * MILES_TO_METERS

    points_proj = points_gdf.to_crs(EQUAL_AREA_CRS)

    # sjoin_nearest with max_distance would only keep the single nearest
    # point per ZCTA; a buffer + join keeps every point in range so repeat
    # storm passes all contribute.
    buffered = centroids.copy()
    buffered["geometry"] = buffered.geometry.buffer(radius_m)
    joined = gpd.sjoin(
        points_proj[["geometry", weight_col]],
        buffered[["zcta5", "geometry"]],
        how="inner",
        predicate="within",
    )

    centroid_by_zcta = centroids.set_index("zcta5").geometry
    joined["centroid"] = joined["zcta5"].map(centroid_by_zcta)
    joined["distance_m"] = joined.geometry.distance(gpd.GeoSeries(joined["centroid"], crs=EQUAL_AREA_CRS))
    joined["decay"] = (1 - joined["distance_m"] / radius_m).clip(lower=0)
    joined["contribution"] = joined[weight_col] * joined["decay"]

    per_zcta = joined.groupby("zcta5")["contribution"].sum().reset_index()
    per_zcta.columns = ["zcta5", "exposure_score"]

    all_zctas = zcta_gdf[["zcta5"]].drop_duplicates()
    result = all_zctas.merge(per_zcta, on="zcta5", how="left")
    result["exposure_score"] = result["exposure_score"].fillna(0)
    return result


def area_apportioned_sum(
    zcta_gdf: gpd.GeoDataFrame,
    regions_gdf: gpd.GeoDataFrame,
    region_key_col: str,
    values: pd.Series,
) -> pd.DataFrame:
    """Areal interpolation of an extensive (count-like) per-region value
    (e.g. county population) onto ZCTAs: assumes uniform density within
    each region and apportions its value by intersection-area fraction of
    the region's total area, then sums per ZCTA. Unlike
    area_weighted_average (for rates/averages), this is for quantities that
    should sum, not average, across a ZCTA's overlapping regions. Used to
    estimate ZCTA population for severe_convective's reporting-bias
    correction.

    Returns [zcta5, value] (value is 0 where no region matched).
    """
    regions_proj = regions_gdf.to_crs(EQUAL_AREA_CRS)[[region_key_col, "geometry"]].copy()
    regions_proj["region_area"] = regions_proj.geometry.area
    regions_proj["value"] = regions_proj[region_key_col].map(values)
    regions_proj = regions_proj.dropna(subset=["value"])

    zcta_proj = zcta_gdf.to_crs(EQUAL_AREA_CRS)[["zcta5", "geometry"]]

    overlay = gpd.overlay(zcta_proj, regions_proj, how="intersection")
    overlay["apportioned"] = overlay["value"] * (overlay.geometry.area / overlay["region_area"])

    per_zcta = overlay.groupby("zcta5")["apportioned"].sum().reset_index()
    all_zctas = zcta_gdf[["zcta5"]].drop_duplicates()
    result = all_zctas.merge(per_zcta, on="zcta5", how="left")
    result["apportioned"] = result["apportioned"].fillna(0)
    return result.rename(columns={"apportioned": "value"})


def area_weighted_average(
    zcta_gdf: gpd.GeoDataFrame,
    regions_gdf: gpd.GeoDataFrame,
    region_key_col: str,
    values: pd.Series,
) -> pd.DataFrame:
    """Area-weighted average of a per-region value (e.g. a county's average
    % time in drought) across each ZCTA's overlapping regions. `values` is
    a Series indexed by region_key_col. Used by Drought (counties).

    Normalizes by the total area fraction actually covered by a matched
    region, so boundary slivers from mismatched simplification between the
    two geometry sources don't bias small ZCTAs' averages toward 0.
    Returns [zcta5, value] (value is NaN where no region matched at all).
    """
    zcta_proj = zcta_gdf.to_crs(EQUAL_AREA_CRS)[["zcta5", "geometry"]].copy()
    zcta_proj["zcta_area"] = zcta_proj.geometry.area

    regions_proj = regions_gdf.to_crs(EQUAL_AREA_CRS)[[region_key_col, "geometry"]]

    overlay = gpd.overlay(zcta_proj, regions_proj, how="intersection")
    overlay["area_frac"] = overlay.geometry.area / overlay["zcta_area"]
    overlay["value"] = overlay[region_key_col].map(values)
    overlay = overlay.dropna(subset=["value"])
    overlay["weighted"] = overlay["value"] * overlay["area_frac"]

    per_zcta = (
        overlay.groupby("zcta5")
        .agg(weighted_sum=("weighted", "sum"), frac_covered=("area_frac", "sum"))
        .reset_index()
    )
    per_zcta["value"] = per_zcta["weighted_sum"] / per_zcta["frac_covered"]

    all_zctas = zcta_gdf[["zcta5"]].drop_duplicates()
    return all_zctas.merge(per_zcta[["zcta5", "value"]], on="zcta5", how="left")


def percent_area_overlay(
    zcta_gdf: gpd.GeoDataFrame,
    overlay_gdf: gpd.GeoDataFrame,
) -> pd.DataFrame:
    """% of each ZCTA's area covered by overlay_gdf's polygons -- the
    generic "point-in-polygon / % area overlay" join for categories that
    are just "share of area inside X" (Flood's SFHA coverage; reusable for
    similar future categories). No dissolve of overlay_gdf first (a
    national dissolve of hundreds of thousands of flood polygons is too
    slow to be worth it) -- source polygons are expected to be
    non-overlapping by construction, and the result is clipped to 100 as a
    safety net against the rare seam/overlap case.

    Returns [zcta5, pct_area] (0-100), one row per ZCTA (0 where no
    overlap).
    """
    zcta_proj = zcta_gdf.to_crs(EQUAL_AREA_CRS)[["zcta5", "geometry"]].copy()
    zcta_proj["zcta_area"] = zcta_proj.geometry.area

    overlay_proj = overlay_gdf.to_crs(EQUAL_AREA_CRS)[["geometry"]]

    overlap = gpd.overlay(zcta_proj, overlay_proj, how="intersection")
    overlap["overlap_area"] = overlap.geometry.area

    per_zcta = overlap.groupby("zcta5")["overlap_area"].sum().reset_index()

    result = zcta_proj[["zcta5", "zcta_area"]].merge(per_zcta, on="zcta5", how="left")
    result["overlap_area"] = result["overlap_area"].fillna(0)
    result["pct_area"] = (result["overlap_area"] / result["zcta_area"] * 100).clip(0, 100)
    return result[["zcta5", "pct_area"]]
