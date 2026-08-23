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
# shared boundary. tippecanoe is not available in this environment (Windows
# dev box, no prebuilt binary), so layers ship as simplified GeoJSON rather
# than vector tiles. Revisit if initial map load / layer-switch performance
# is unacceptable (see Phase 8).
COVERAGE_SIMPLIFY_TOLERANCE_M = 300

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
