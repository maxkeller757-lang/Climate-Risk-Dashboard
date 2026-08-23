# Zip-Code Climate & Hazard Risk Dashboard

A dashboard that shows a 0-100 hazard risk score per US zip code across 8
categories (severe convective weather, flood, wildfire, hurricane, winter
weather, drought, extreme heat, seismic) plus a composite score, derived from
real historical hazard data (2015-2024) via an offline GIS pipeline.

**Status: all 8 categories + composite live**, CONUS-wide (~33,010 ZCTAs).
Map, zip search, click-to-inspect, and methodology modal all working
end-to-end against real pre-computed data.

## Repo layout

```
pipeline/   Offline Python GIS pipeline. Downloads raw hazard data, does the
            spatial joins / zonal stats, writes pre-computed scores. Nothing
            here runs at request time.
backend/    FastAPI app that only reads pipeline/ output -- no live
            geoprocessing.
frontend/   React + Vite + MapLibre GL dashboard.
data/       Pipeline output: zcta_geometries.parquet, zip_scores.parquet,
            layers/<category>.geojson. Gitignored (regenerate via the
            pipeline, don't commit).
scripts/    Dev tooling, e.g. regenerating the trimmed basemap style.
```

## Running it

```bash
# one-time: install the Python geo stack + Node (via pixi)
pixi install

# full pipeline (writes data/) -- long: live FEMA/USDM queries per county,
# 10 years of gridMET. Safe to re-run after a partial failure -- each
# category caches its raw source data (per-county/per-year) on disk.
pixi run python pipeline/refresh_all.py

# or run one category at a time, e.g.:
pixi run python pipeline/fetch_zcta_geometries.py
pixi run python pipeline/severe_convective.py
# ...
pixi run python pipeline/composite.py   # after every category has run

# backend (localhost:8000)
pixi run uvicorn backend.app.main:app --port 8000
# backend tests:
pixi run python -m pytest backend/tests/ -v
# pipeline sanity checks (known high/low risk ZCTAs vs. actual scores):
pixi run python pipeline/validate_scores.py
# layer completeness + render cost (CONUS coverage, holes, file sizes):
pixi run python pipeline/verify_layers.py

# frontend (localhost:5173) -- separate terminal
cd frontend && pixi run --manifest-path ../pixi.toml npm run dev
```

## Data sources & methodology

All scores are percentile ranks (0-100) of a raw metric, computed once
offline and never recomputed at request time. Percentile ranking makes the 8
categories comparable on the same scale even though their raw units differ
wildly (event counts vs. % area vs. temperature days).

| Category | Source | Window | Method |
|---|---|---|---|
| Severe Convective | NCEI Storm Events (Tornado/Hail/TStorm Wind) | 2015-2024 | 15mi buffer around ZCTA centroid, severity-weighted count, detrended against population density |
| Winter Weather | NCEI Storm Events (Winter Storm/Ice Storm/Heavy Snow/Blizzard) | 2015-2024 | % area overlay against real NWS forecast zone polygons, severity-weighted |
| Flood | FEMA NFHL (live ArcGIS service) | current | % of ZCTA area in SFHA Zone A/AE/V/VE |
| Wildfire | USFS Wildfire Hazard Potential + MTBS burn perimeters | latest model + 2015-2024 | 70% zonal-mean WHP + 30% historical burn intersection count |
| Hurricane | NOAA HURDAT2 | 2015-2024 | Wind-speed-squared-weighted track point proximity, 150mi linear decay |
| Drought | U.S. Drought Monitor county statistics | 2015-2024 | Average % time in D0-or-worse, area-weighted county -> ZCTA |
| Extreme Heat | gridMET daily max temp + min RH | 2015-2024 | 60% days >90F, 40% days heat index >100F (Rothfusz regression) |
| Seismic | USGS National Seismic Hazard Model (2018) + Volcanic Threat Assessment | latest model | 80% zonal-mean PGA + 20% distance-decayed volcano threat |

**WHP and the USGS seismic hazard model are point-in-time hazard models, not
event histories** -- they use the latest published model version rather than
a 2015-2024 rolling aggregation, since there's no annual time series to
aggregate.

**Winter Weather uses real NWS zone polygons, not a point buffer**: NCEI
records Winter Storm/Ice Storm/Heavy Snow/Blizzard events by NWS public
forecast zone (`CZ_TYPE='Z'`), not lat/lon -- confirmed empirically (0% of
these events carry a usable point location in NCEI's bulk data, unlike
Tornado/Hail/Wind). Fixed by downloading NOAA's real public-zone shapefile
(`pipeline/sources/nws_zones.py`) and doing a proper % area overlay
(`spatial.zone_overlay_score`), pulling Flood's polygon-overlay method
forward a bit early.

**Severe Convective is detrended against population density**: NCEI Storm
Events is a human-report database, so raw report density tracks population
as much as real storm activity -- every major metro looked like a hazard
hotspot before this fix. `scoring.population_bias_correct` fits
`log1p(severity) ~ log1p(population_density)` (Census county population,
areally apportioned onto ZCTAs) and keeps the residual as the raw metric, a
standard technique in severe-weather reporting-bias literature. This does
not (and cannot) fully remove reporting bias -- rural areas can still
underreport hazard below what a resident would notice and report -- but it
removes the population-driven trend, which was the dominant, statistically
correctable component.

**Extreme Heat uses gridMET alone for both sub-components**, not gridMET +
nClimGrid-Daily as originally scoped -- both measure daily max temp, so
using one consistent CONUS daily dataset for both the raw-threshold and
heat-index components avoids pulling two redundant 10-year daily grids
without compromising either metric. The Rothfusz regression was validated
against NWS's published heat index chart (see `pipeline/sources/heat_index.py`)
before the full run -- catching a transcription bug in one coefficient
(off by 1000x) that would have silently produced nonsense values.

**Seismic's volcano component** is a small, hand-curated table of CONUS
Cascades/Yellowstone/Long Valley volcanic centers from the 2018 USGS
National Volcanic Threat Assessment's "Very High"/"High" tiers (see
`pipeline/sources/volcanoes.py`) -- USGS's own published GIS product for
this ships only as a detailed ArcGIS Pro hazard-zone layer, overkill for
"is this ZCTA near an active volcanic center."

**Severity weighting** (see `pipeline/sources/ncei_storm_events.py`) is a v1
heuristic (EF-scale / magnitude-based where available, deaths/injuries as a
proxy otherwise), not a validated meteorological index. Worth revisiting
against domain literature before treating scores as authoritative.

**Composite score**: a weighted power mean (Holder mean, exponent 3), not a
plain weighted average, of the 8 category percentiles -- both the weights
and the exponent live in `pipeline/composite_weights.json`, not hardcoded,
so retuning either is a config change. v1's plain equal-weighted average let
a place with several categories in the 90s (e.g. Miami Beach: Flood=99,
Hurricane=96) get dragged down to a mediocre composite (23) by unrelated low
categories; raising each score to a power before averaging makes already-high
scores dominate, so Miami Beach now composites to 80. Weights were also
revised off equal (12.5% each) to Drought and Seismic at 5% each (Drought
overlaps heavily with Wildfire/Heat's own signal; Seismic is a comparatively
rare, localized threat nationally), redistributed across the other 6 at 15%
each.

**Zip -> ZCTA mapping**: most USPS zip codes numerically match a ZCTA5 code
directly. PO-box-only zips and zips split across multiple ZCTAs are not yet
handled (planned: UDS Mapper's free ZIP-to-ZCTA crosswalk) -- see
`backend/app/zip_lookup.py`.

## ZCTA geometry fixes

Census TIGER's raw ZCTA5 polygons, if simplified naively (per-polygon
`.simplify()`), produce slivers and overlaps at every shared boundary
(adjacent polygons' edges drift apart independently) and don't cover 100%
of CONUS land (some low-population land has no assigned ZCTA at all,
showing as a blank hole). `pipeline/fetch_zcta_geometries.py` fixes both:

1. **Topology-aware simplification** via `GeoSeries.simplify_coverage()`
   (shapely/geopandas, requires GEOS coverage-simplify support) instead of
   per-polygon simplify -- shared edges stay shared, no new slivers.
2. **Gap fill**: the gap between the ZCTA union and a real land mask
   (dissolved Census county boundaries, which do fully tile CONUS land) is
   computed, and each gap piece is merged into its nearest ZCTA by boundary
   distance.

## No-ZIP land areas

Not all CONUS land has a ZIP code -- tidal marsh, barrier islands, and
unaddressed parcels have no ZCTA5, and Census only assigns ZCTAs where
mail is delivered. Those areas get their own `NOZIP-#####` polygons
(deliberately not 5 digits, so they can never be confused with or searched
as a real ZIP). They are real geometry, so the category modules score them
directly like any other polygon -- a marsh island off Charleston gets its
own hurricane and flood exposure computed, not a placeholder.
`fill_nozip_scores.py` runs afterwards purely as a safety net, filling any
polygon a category legitimately had no data for (raster sources such as
WHP have no value over open water) from a shared-boundary-weighted mean of
its neighbours.

## Map rendering

Basemap is a trimmed OpenFreeMap "liberty" vector style (~19 layers of ~111
kept -- interstates, park/forest/water/urban landuse, minimal else; see
`scripts/build_basemap_style.py`) -- free, no API key, no rate limit.
`tippecanoe` (vector tiles) is not available in this Windows dev
environment, so category layers ship as simplified GeoJSON instead.

Render geometry is kept separate from analysis geometry
(`build_render_geometries.py` -> `zcta_geometries_render.parquet`).
Scoring needs accurate polygons; the browser does not, since at CONUS zoom
a ZCTA is a few pixels wide. Simplifying once for display cut each layer
from 2.25M vertices to 1.11M, and layers are written with the GeoJSON
writer's `COORDINATE_PRECISION=5` (~1m) rather than 14 decimal places of
sub-micrometer noise. Together: **101MB -> 34MB per layer.**

Two rendering traps worth knowing about, both of which silently punched
holes in the map before being caught:
  * `shapely.set_precision()` snaps to a grid and *deletes* polygons
    smaller than that grid. Use the writer's `COORDINATE_PRECISION`
    instead -- it only formats output, leaving geometry intact.
  * A polygon with a null score renders at the bottom of the colour ramp,
    which is visually identical to a hole. `write_layer_geojson` now
    raises on any missing score or empty geometry rather than
    `fillna(0)`-ing the problem out of sight.

`pipeline/verify_layers.py` checks both, plus that the polygons actually
blanket CONUS land (measured against the Census county land mask), and
reports per-layer vertex count and file size.

The map is bounded to CONUS + ~5deg padding (not the whole globe) and fit
to that box on load, so the initial view is always CONUS-centered
regardless of viewport aspect ratio.

## Open items

- Deployment target (live hosting vs. local/demo-video) -- not yet decided.
