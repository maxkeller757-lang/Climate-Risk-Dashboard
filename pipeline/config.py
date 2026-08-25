"""Shared paths and constants for the hazard data pipeline."""
from pathlib import Path

PIPELINE_DIR = Path(__file__).resolve().parent
ROOT_DIR = PIPELINE_DIR.parent
DATA_DIR = ROOT_DIR / "data"
RAW_DIR = DATA_DIR / "raw"
LAYERS_DIR = DATA_DIR / "layers"

ZCTA_GEOMETRIES_PATH = DATA_DIR / "zcta_geometries.parquet"
# Coarser copy of the above, used only for drawing the map -- see
# build_render_geometries.py. Analysis (areas, overlays, zonal stats)
# always uses ZCTA_GEOMETRIES_PATH.
ZCTA_RENDER_GEOMETRIES_PATH = DATA_DIR / "zcta_geometries_render.parquet"
ZIP_SCORES_PATH = DATA_DIR / "zip_scores.parquet"
# USPS ZIP -> ZCTA5 lookup used by the API's zip search; see
# build_zip_crosswalk.py.
ZIP_TO_ZCTA_PATH = DATA_DIR / "zip_to_zcta.parquet"
COMPOSITE_WEIGHTS_PATH = PIPELINE_DIR / "composite_weights.json"

# 10-year historical window used for all event-history-based categories
# (Severe Convective, Winter Weather, Hurricane, Drought, Heat). WHP and the
# USGS seismic hazard model are point-in-time model outputs, not event
# histories, and are exempt from this window (see their ingestion modules).
START_YEAR = 2015
END_YEAR = 2024

# CRS used for all area/distance calculations that need to be in meters
# (CONUS Albers Equal Area).
EQUAL_AREA_CRS = "EPSG:5070"
# CRS used for final web map output.
WEB_CRS = "EPSG:4326"

# ZCTA5 geometry simplification tolerance (meters, in EQUAL_AREA_CRS),
# applied via GeoSeries.simplify_coverage() -- a topology-aware
# simplification that keeps shared ZCTA-to-ZCTA edges identical, avoiding
# the slivers/overlaps a naive per-polygon .simplify() introduces at every
# shared boundary.
#
# This is the geometry every hazard score is computed against, so the
# tolerance has to stay well below the size of the smallest ZCTA. It was
# 300m, which is wider than a single-building urban ZCTA is across: 10271
# (Wall Street, ~87m across) collapsed from 6,779 m^2 to 1 m^2, and ZCTAs
# under 0.5 km^2 kept a median of just 68% of their area. Those polygons
# weren't smoothed, they were destroyed, and their scores -- flood
# especially, being a share-of-area metric -- were computed on the wreckage.
# See pipeline/verify_zcta_fidelity.py, which measures this against the raw
# Census source.
#
# Measured tradeoff (vertices as a share of the raw 50.0M, and the median
# area retained by sub-0.5 km^2 ZCTAs):
#   300m -> 2.0M (4.0%), 68.0% area kept   <- original value, broken
#   100m -> 4.6M (9.2%), 98.6% area kept
#    50m -> 7.7M (15.3%), 99.8% area kept
#    25m -> 12.5M (25.0%), 99.9% area kept  <- current
#
# 25m was chosen over the alternative of holding small ZCTAs out of the
# simplification entirely (see SMALL_ZCTA_AREA_M2). That alternative was
# built and measured: it came to 13.81M vertices against 13.76M for a
# uniform 25m pass -- no cheaper, because preserving the small polygons'
# edges also means preserving the whole CONUS coastline at raw resolution,
# and that coastline detail buys no analytical accuracy. Uniform 25m costs
# the same, needs one code path instead of two, carries no risk of slivers
# where preserved and simplified polygons meet, and is strictly more
# faithful on large ZCTAs (25m rather than 100m).
#
# Note this does NOT drive the size of what the browser downloads --
# RENDER_SIMPLIFY_TOLERANCE_M below governs that independently, so
# changing this costs pipeline compute time, not page load time.
COVERAGE_SIMPLIFY_TOLERANCE_M = 25

# Render-only simplification (meters), applied on top of the above by
# build_render_geometries.py to produce the map's polygons. At CONUS zoom
# a ZCTA is only a few pixels across, so detail below this is invisible
# but still costs download + parse time in the browser. Raise for smaller
# files / faster layer switches, lower if polygons look visibly angular
# when zoomed in.
RENDER_SIMPLIFY_TOLERANCE_M = 800

CENSUS_ZCTA_URL = (
    "https://www2.census.gov/geo/tiger/TIGER2023/ZCTA520/"
    "tl_2023_us_zcta520.zip"
)

# CONUS bounding box, used to drop AK/HI/PR/territories from the ZCTA layer
# (v1 scope is CONUS-only per the project brief).
CONUS_BBOX = (-125.0, 24.0, -66.0, 50.0)  # (minx, miny, maxx, maxy)

# Morphological-closing buffer (meters) used to find small coastal gaps
# (tidal marsh, barrier-island channels) that the county-boundary land
# mask misses -- county cartographic boundaries are water-clipped along
# the coast the same way ZCTA5 is, so a straight land-mask diff sees no
# gap there at all. Buffering the ZCTA union out then back in by this much
# closes gaps narrower than 2x this distance without claiming genuinely
# open water (bays/sounds wider than this stay open). ~5km bridges typical
# Lowcountry marsh creeks without spanning multi-mile sounds.
COASTAL_CLOSING_BUFFER_M = 5000

# Prefix for synthetic ZCTA5-shaped IDs assigned to gap-filled land that
# has no real ZIP code (marsh, barrier islands, other unaddressed land).
# Deliberately not 5 digits, so it can never collide with or be mistaken
# for a real ZCTA5/zip code -- see zip_lookup.py.
NO_ZIP_PREFIX = "NOZIP-"

# Smallest gap polygon worth keeping (square meters). Below this they are
# topological noise from the gap-detection step, not real land -- a few
# square meters of rounding residue along a boundary. They also cannot
# survive the GeoJSON writer's coordinate rounding, collapsing to empty
# geometry and tripping the "hole in the map" check for no reason.
MIN_GAP_AREA_M2 = 1000

# ZCTAs below this area are held out of coverage simplification entirely
# and kept at full source resolution (see
# fetch_zcta_geometries._simplify_preserving_small()).
#
# Disabled -- set to 0 -- because it turned out not to be worth it. The
# mechanism works, but at 2 km^2 it produced 13.81M vertices against
# 13.76M for simply running the whole coverage at 25m: preserving the
# small polygons' edges requires simplify_boundary=False, which also
# pins the entire CONUS coastline at raw resolution. Same cost, more
# moving parts. Kept because it becomes worthwhile again if
# COVERAGE_SIMPLIFY_TOLERANCE_M is ever raised back toward 100m+, where
# small ZCTAs start being destroyed and the coastline penalty is the
# lesser evil.
SMALL_ZCTA_AREA_M2 = 0

# Oversized no-ZIP gap areas get subdivided until every piece is under
# this many times the median real ZCTA area. TIGER leaves large tracts of
# public land unassigned, and they merge into single enormous blobs -- one
# reached 239,912 km^2, larger than Wyoming. A single hazard score
# averaged over that is meaningless, so they're split into pieces of
# roughly zip-code scale. See subdivide_large_gaps.py.
MAX_GAP_AREA_MEDIAN_MULTIPLE = 5

# After clipping no-ZIP gap areas against open water (see
# clip_gap_water.py), a gap polygon whose remaining land area falls below
# this is dropped rather than kept as a tiny remnant. This is a
# render-only cleanup -- it runs on zcta_geometries_render.parquet, not
# the analysis geometry, so it never touches a hazard score.
#
# 0.05 km^2 (500m x 100m, roughly) was chosen against the project's own
# render-visibility logic: at CONUS zoom a ZCTA is "a few pixels wide"
# (see RENDER_SIMPLIFY_TOLERANCE_M above), so anything under this scale
# is at or below single-pixel size and not worth rendering as its own
# shape. This is deliberately much larger than MIN_GAP_AREA_M2 (1,000
# m^2), which exists only to catch near-zero topological noise, not to
# make a visual-scale judgement.
WATER_CLIP_SLIVER_AREA_M2 = 50_000
