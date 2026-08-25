# Zip-Code Climate & Hazard Risk Dashboard

A dashboard that shows a 0-100 hazard risk score per US zip code across 9
categories (severe convective weather, flood, wildfire, hurricane, winter
weather, drought, extreme heat, seismic, air quality) plus a composite
score, derived from real historical hazard data (mostly 2015-2024; see the
per-category windows below) via an offline GIS pipeline.

**Status: all 9 categories + composite live**, CONUS-wide (38,072 polygons).
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
offline and never recomputed at request time. Percentile ranking makes the 9
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
| Air Quality | CDC/EPA fused daily county PM2.5 surface | 2015-2021 | Avg days/year with county mean PM2.5 above 35.4 ug/m3 (AQI > 100) |

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

**Air Quality uses a fused surface, not raw monitor data.** EPA's AQS
monitor summaries have the metric we want but only cover 949 of 3,109
CONUS counties (31% of counties, 43% of land, 78% of population) -- two
thirds of the map would have been interpolated, and because monitors are
sited in cities that interpolation would have biased rural air *upward*.
The CDC/EPA fused surface blends those same monitors with a CMAQ model to
give a daily value for every county, so the layer is measured-and-modelled
everywhere instead of measured in cities and guessed elsewhere. Being
daily, it also preserves the "days above a threshold" metric that a
satellite annual-mean product would have forced us to abandon. Its window
is 2015-2021: the source ends 31 Oct 2022, and including a partial year
would undercount.

One join hazard worth recording: Connecticut replaced its eight counties
with nine Planning Regions in 2022, so the 2023 Census county file and
this 2015-2021 dataset share no Connecticut GEOIDs at all. The join
matched nothing and silently dropped the entire state until
`load_counties_legacy_ct()` was added -- a reminder that a county-FIPS
join against a pre-2022 dataset fails quietly rather than loudly.

**Composite score**: a weighted power mean (Holder mean, exponent 3), not a
plain weighted average, of the 9 category percentiles -- both the weights
and the exponent live in `pipeline/composite_weights.json`, not hardcoded,
so retuning either is a config change. v1's plain equal-weighted average let
a place with several categories in the 90s (e.g. Miami Beach: Flood=99,
Hurricane=96) get dragged down to a mediocre composite (23) by unrelated low
categories; raising each score to a power before averaging makes already-high
scores dominate, so Miami Beach now composites to 80. Weights were also
revised off equal: Drought, Seismic and Air Quality carry 0.05 against
0.15 for the other six, so each contributes one third as much. Drought
overlaps heavily with Wildfire/Heat's own signal in the same places;
Seismic is a comparatively rare, localized threat nationally; and Air
Quality is chronic-exposure rather than acute-event risk, so it belongs as
a modifier rather than a driver. The values are relative -- composite.py
normalizes by their sum, so they need not total 1.0.

**Zip -> ZCTA mapping**: most USPS zip codes numerically match a ZCTA5
code directly, but ~9,200 PO-box-only and large-volume-customer zips have
no land area of their own, so their code is never a ZCTA -- 78381
(Rockport TX) sits inside ZCTA 78382. Those used to 404. A crosswalk
(`pipeline/build_zip_crosswalk.py` -> `data/zip_to_zcta.parquet`) now
resolves them, covering **7,135 zips that direct matching cannot**;
direct matching stays as a fallback so a zip newer than the crosswalk
still works. The detail panel shows both the zip and the ZCTA it mapped
to, so a redirected lookup is visible rather than silent.

Source note: the obvious choice was UDS Mapper's crosswalk, which this
project originally planned for, but the AAFP sunset UDS Mapper in early
2024 and its download is gone. HRSA publishes the same mapping, still
maintained, as a direct .xlsx with no auth.

Failures are now distinguished rather than lumped into one "not found":
`unknown_zip` (no such zip), `no_zcta` (real zip, but Census defines no
ZCTA -- a handful of territory zips), and `outside_conus` (real zip and
real ZCTA, just outside this project's scope, e.g. Honolulu). "We don't
cover that" and "that isn't a zip" are different answers.

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

## The bottom-right panel

Two panels share that slot, and which one shows is decided by whichever
the user acted on most recently:

* Selected a **polygon** (map click, zip search, or a row in the table
  below) -> that polygon's full category breakdown.
* Selected a **layer** -> a table of the three highest-risk zip codes for
  that layer, each with its county/state.

The reason for the swap is that the two selections ask different
questions. Picking a layer asks "where is this hazard worst?", which the
breakdown of whatever polygon happened to be clicked earlier cannot
answer; picking a polygon asks "what is it like *here*?", which the
national table cannot. Zip codes in the table are clickable and drill
through to the breakdown, which also flips focus back to the polygon.

The table excludes no-ZIP gap areas. They are real land carrying real
scores, but "the three worst places for wildfire" naming three unnamed
patches of national forest helps nobody, and on some layers they are
numerous enough near the top to crowd out every actual zip code.

**Ranking order**: score descending, ties broken by apportioned population
descending, then zip ascending. A raw-metric tiebreak was tried first and
turned out to be dead code: `percentile_rank()` derives score from raw via
`rank(pct=True)`, a strictly monotonic map, so two rows can never share a
score while differing in raw -- sorting by `[score, raw]` is identical to
sorting by `[score]` alone. What looked like ties in the UI (three zips
all reading "100.0") were never ties at all, just `round(score, 1)`
collapsing distinct values (e.g. 99.9946 and 99.9917 both round to 100.0)
-- fixed by showing 3 decimal places in this table specifically.

Real ties do exist, though, wherever the raw metric hits a hard ceiling --
21 ZCTAs sit at exactly 100% of area in a flood zone, 25 at the air
quality category's day-count cap. For those, population (areally
apportioned from county totals the same way `severe_convective.py`
apportions it for reporting-bias correction) is the tiebreak that means
something: more people exposed ranks first. Zip code makes whatever's
left fully deterministic.

Each table row also carries a county name, computed the same way as the
gap-area state attribution (dominant-area overlay against Census county
polygons) -- so a result reads as "Miami-Dade County, FL" rather than a
bare zip code.

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

Layers are then pre-gzipped at pipeline write time and served as the
compressed sibling to any client sending `Accept-Encoding: gzip`, taking
**34MB -> 8.4MB on the wire (24.6%)**. Compression happens once during the
build, not per request, for two reasons: `FileResponse` sends large files
through uvicorn's zero-copy `pathsend`, so they never reach body-based
middleware like `GZipMiddleware` at all; and compressing 34MB live would
cost 1-3s of blocking CPU on every layer switch, stalling the event loop
for concurrent requests. `GZipMiddleware` is still registered, but only
earns its keep on the small dynamic JSON endpoints.

Measured on localhost, a layer switch is ~190ms click-to-bytes-delivered
with **zero main-thread blocking** -- MapLibre parses GeoJSON on a worker,
so the UI stays responsive while 32.6MB is decoded. Localhost has no
bandwidth ceiling, so the compression matters far more in the real world:
on a 25 Mbps connection the same payload drops from roughly 11s to 2.7s.

Compression is where the remaining easy wins have run out; the next real
step would be vector tiles (MVT/PMTiles), which would fetch only the
polygons in view instead of all 38k every time.

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

- **Validate the storm severity weighting.** `severity_weight()` in
  `pipeline/sources/ncei_storm_events.py` is a hand-rolled heuristic --
  EF-scale for tornadoes, magnitude for hail and wind, deaths and injuries
  as a proxy for winter events, since NCEI leaves MAGNITUDE unpopulated
  for those. It has never been checked against the severe-weather
  literature, and it drives Severe Convective and Winter Weather outright.
  Deliberately deferred, not overlooked.
- **Small-ZCTA fidelity is improved but not perfect.** At a 25m
  simplification tolerance the sub-0.5 km^2 band still doesn't match the
  raw source exactly; a handful of single-building urban ZCTAs (10271 on
  Wall Street is ~87m across) remain the hardest cases. Their flood score,
  being share-of-area, is the most sensitive to it.
- **Air Quality covers 2015-2021**, everything else 2015-2024 -- the CDC
  source ends 31 Oct 2022 and a partial year would undercount. The
  composite therefore blends a 7-year and a 10-year climatology.
- Deployment target (live hosting vs. local/demo-video) -- not yet decided.
- Vector tiles (MVT/PMTiles) are the next real performance step, now that
  gzip has taken the cheap win.
