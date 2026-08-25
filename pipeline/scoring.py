"""
Shared scoring utilities: percentile-ranking a raw metric to a 0-100 score,
merging category scores into the shared zip_scores table, and writing the
per-category GeoJSON layer the frontend map reads.
"""
import gzip
import os
import time
from pathlib import Path

import geopandas as gpd
import numpy as np
import pandas as pd

from config import (
    LAYERS_DIR,
    NO_ZIP_PREFIX,
    ZCTA_GEOMETRIES_PATH,
    ZCTA_RENDER_GEOMETRIES_PATH,
    ZIP_SCORES_PATH,
)


def _replace_with_retry(src: Path, dst: Path, attempts: int = 6, delay_s: float = 5.0) -> None:
    """os.replace(), retrying on Windows' "file in use" errors. A live
    backend actively streaming this exact file to a browser (FileResponse
    over uvicorn's zero-copy pathsend) holds an OS-level lock on it for the
    duration of that transfer -- a large layer download can take a few
    seconds, during which even a rename fails. Rerunning the pipeline while
    the dashboard is open elsewhere is a completely normal thing to do, so
    this should recover on its own rather than crashing the whole run."""
    for attempt in range(1, attempts + 1):
        try:
            os.replace(src, dst)
            return
        except PermissionError:
            if attempt == attempts:
                raise
            print(f"  {dst.name} is in use (likely being downloaded right now) -- retry {attempt}/{attempts} in {delay_s:.0f}s...")
            time.sleep(delay_s)


def percentile_rank(df: pd.DataFrame, raw_col: str, score_col: str = "score") -> pd.DataFrame:
    """0-100 percentile rank of raw_col, ranked against real ZCTAs only.

    The reference population is deliberately *not* every row. Roughly 15%
    of polygons are NOZIP-* gap areas -- marsh, barrier islands,
    unaddressed land -- and ranking against those makes a score mean
    "higher than N% of polygons, including uninhabited marsh" when the UI
    presents it as a comparison between zip codes. It also biases whole
    categories: coastal marsh scores high on flood and hurricane, so
    including it pushes real coastal ZCTAs' percentiles down.

    Gap areas still get a score, and still a meaningful one -- they have
    real computed raw values, so they're placed by where that value falls
    within the real-ZCTA distribution. They just don't get a vote in
    defining it.
    """
    df = df.copy()

    if "zcta5" not in df.columns:
        raise KeyError(
            "percentile_rank needs a zcta5 column to separate real ZCTAs from "
            "NOZIP-* gap areas."
        )

    is_gap = df["zcta5"].astype(str).str.startswith(NO_ZIP_PREFIX)
    real_values = df.loc[~is_gap, raw_col]
    if real_values.empty:
        raise ValueError("No real ZCTAs to rank against.")

    scores = pd.Series(np.nan, index=df.index, dtype="float64")
    # Real ZCTAs: ordinary percentile rank within their own population.
    scores.loc[~is_gap] = real_values.rank(pct=True) * 100

    # Gap areas: where each value would sit in that same distribution.
    # searchsorted on both sides and averaging mirrors pandas' "average"
    # tie handling, so a gap area tied with real ZCTAs lands at the same
    # percentile they do rather than at the edge of the tie block.
    if is_gap.any():
        ref = np.sort(real_values.to_numpy())
        gap_values = df.loc[is_gap, raw_col].to_numpy()
        left = np.searchsorted(ref, gap_values, side="left")
        right = np.searchsorted(ref, gap_values, side="right")
        scores.loc[is_gap] = ((left + right) / 2.0) / len(ref) * 100

    df[score_col] = scores
    return df


def population_bias_correct(
    df: pd.DataFrame, raw_col: str, density_col: str, out_col: str = "bias_corrected"
) -> pd.DataFrame:
    """Removes the population-density trend from a human-report-based raw
    metric via log-log OLS detrending: fit log1p(raw) ~ log1p(density) and
    keep the residual as the new raw metric.

    Why: report-based hazard data (e.g. NCEI Storm Events) is denser where
    more people are around to see and report an event, not necessarily
    where the actual hazard is worse -- a well-documented bias in severe
    weather climatology (see e.g. Verbout et al. 2006 on tornado reporting
    bias). A ZCTA that reports more events than its population alone would
    predict gets a positive residual (genuinely elevated hazard); one that
    reports fewer gets negative. Residuals, not raw values, are what get
    percentile-ranked afterward -- the sign/scale of the residual doesn't
    matter, only its rank order.

    This does not (and cannot) fully remove reporting bias -- rural areas
    can still underreport hazard below what a resident would notice and
    call in -- but it removes the population-driven trend, which was the
    dominant, statistically correctable component.
    """
    df = df.copy()
    log_density = np.log1p(df[density_col].clip(lower=0))
    log_raw = np.log1p(df[raw_col].clip(lower=0))

    slope, intercept = np.polyfit(log_density, log_raw, 1)
    predicted = slope * log_density + intercept
    df[out_col] = log_raw - predicted
    return df


def contrast_stretch(scores: pd.Series, power: float = 2.5) -> pd.Series:
    """S-curve contrast stretch on an already-0-100 percentile score:
    pushes above-median values higher and below-median values lower, with
    fixed points at 0, 50, and 100 (a ZCTA already at the median stays
    there). Higher `power` concentrates more aggressively toward the
    extremes. Used to make a category read as more regionally concentrated
    without pulling new data -- e.g. Hurricane, where the underlying
    percentile rank already separates coastal from interior ZCTAs but the
    spec called for the map to read as more sharply concentrated on the
    coast.

    This must run AFTER percentile_rank, and nothing should re-rank its
    output: percentile-ranking a monotonic transform of a uniform variable
    just undoes the transform (rank order is unchanged, so re-ranking
    reproduces the original uniform distribution).
    """
    u = (scores / 100.0).clip(1e-9, 1 - 1e-9)
    y = u**power / (u**power + (1 - u) ** power)
    return y * 100.0


def upsert_zip_scores(category: str, scores: pd.DataFrame, raw_col: str) -> None:
    """Merge one category's [zcta5, raw_col, score] into the shared
    zip_scores table (data/zip_scores.parquet), creating it on first call
    and overwriting that category's columns on rerun."""
    zcta = gpd.read_parquet(ZCTA_GEOMETRIES_PATH)[["zcta5"]]
    if ZIP_SCORES_PATH.exists():
        table = pd.read_parquet(ZIP_SCORES_PATH)
    else:
        table = zcta.copy()

    raw_out, score_out = f"{category}_raw", f"{category}_score"
    renamed = scores[["zcta5", raw_col, "score"]].rename(
        columns={raw_col: raw_out, "score": score_out}
    )

    table = table.drop(columns=[raw_out, score_out], errors="ignore")
    # Outer, not left: a left join silently drops ZCTAs that exist in this
    # category's results but not yet in the stored table, so the table
    # could never pick up ZCTAs added by a later geometry rebuild -- they
    # stayed permanently unscored and rendered as holes in the map.
    table = table.merge(renamed, on="zcta5", how="outer")
    ZIP_SCORES_PATH.parent.mkdir(parents=True, exist_ok=True)
    table.to_parquet(ZIP_SCORES_PATH)
    print(f"Updated {ZIP_SCORES_PATH} with {category} scores for {len(renamed)} ZCTAs")


def write_layer_geojson(category: str, color_hex: str) -> None:
    """Join the category's score onto ZCTA geometry and write
    data/layers/<category>.geojson for the frontend map to render.

    Every polygon must come out with a real score: a ZCTA with no score
    row would render at the ramp's low end and read as a hole in the map,
    which is indistinguishable from missing data. NOZIP-* gap polygons get
    interpolated scores upstream (fill_nozip_scores.py); anything still
    unscored here is a bug, so this raises rather than silently fillna(0).
    """
    # During a full rebuild the layers can't be written until every
    # category (and the NOZIP fill) has run, because a layer needs a score
    # for every polygon. Setting SKIP_LAYER_WRITE=1 lets the category
    # modules just update zip_scores and leave rendering to a final pass.
    if os.environ.get("SKIP_LAYER_WRITE"):
        print(f"SKIP_LAYER_WRITE set -- skipping {category} layer write")
        return

    zcta = gpd.read_parquet(ZCTA_RENDER_GEOMETRIES_PATH)
    table = pd.read_parquet(ZIP_SCORES_PATH)
    score_col = f"{category}_score"

    merged = zcta.merge(table[["zcta5", score_col]], on="zcta5", how="left")
    merged = merged.rename(columns={score_col: "score"})

    missing = merged["score"].isna()
    if missing.any():
        raise RuntimeError(
            f"{missing.sum()} polygon(s) have no {category} score (e.g. "
            f"{merged.loc[missing, 'zcta5'].head(5).tolist()}). Run "
            "pipeline/fill_nozip_scores.py after the category modules."
        )

    empty = merged.geometry.is_empty | merged.geometry.isna()
    if empty.any():
        raise RuntimeError(
            f"{empty.sum()} polygon(s) have empty geometry (e.g. "
            f"{merged.loc[empty, 'zcta5'].head(5).tolist()}) -- these would "
            "render as holes in CONUS."
        )

    merged["color"] = color_hex

    LAYERS_DIR.mkdir(parents=True, exist_ok=True)
    out_path = LAYERS_DIR / f"{category}.geojson"
    # Write to a temp file and os.replace() into place, rather than having
    # GDAL overwrite out_path directly: on Windows, whatever last held the
    # file open (an antivirus scan, a lingering FileResponse to a browser
    # tab, etc.) can keep an overwrite-in-place PermissionError'ing for a
    # while after the reader is gone. os.replace is atomic and doesn't
    # require the old file to be unlocked, only renameable.
    tmp_path = out_path.with_name(out_path.name + ".tmp")
    # Coordinate rounding is done by the GeoJSON writer (COORDINATE_PRECISION),
    # not shapely.set_precision(): set_precision snaps to a grid and
    # *collapses* polygons smaller than that grid to empty geometry -- it
    # silently deleted 51 small urban ZCTAs, punching real holes in the map.
    # The writer option only formats the output coordinates, leaving the
    # in-memory geometry (and every polygon's existence) untouched. Source
    # coords carry ~14 decimals (sub-micrometer); 5 decimals is ~1m, still
    # far finer than COVERAGE_SIMPLIFY_TOLERANCE_M.
    merged[["zcta5", "score", "color", "geometry"]].to_file(
        tmp_path, driver="GeoJSON", COORDINATE_PRECISION=5
    )
    _replace_with_retry(tmp_path, out_path)
    print(f"Wrote {out_path} ({out_path.stat().st_size / 1e6:.1f} MB)")

    # Pre-gzip once here, not per-request: this text compresses to ~25% of
    # its size, but gzipping 34MB takes 1-3s of blocking CPU -- fine to pay
    # once at build time, not on every layer-switch request (that would
    # also stall uvicorn's event loop for other requests). The API serves
    # this file directly when the client sends Accept-Encoding: gzip.
    gz_path = out_path.with_name(out_path.name + ".gz")
    with open(out_path, "rb") as src, gzip.open(gz_path, "wb", compresslevel=9) as dst:
        dst.write(src.read())
    print(f"Wrote {gz_path} ({gz_path.stat().st_size / 1e6:.1f} MB)")
