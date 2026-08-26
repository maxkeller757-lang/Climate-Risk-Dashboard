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
| Winter Weather | gridMET daily precipitation + max temp | 2015-2024 | Avg days/year with >=0.01in precip and max temp <=32F |
| Flood | FEMA NFHL (live ArcGIS service) | current | % of ZCTA area in SFHA Zone A/AE/V/VE |
| Wildfire | USFS Wildfire Hazard Potential + MTBS burn perimeters | latest model + 2015-2024 | 70% zonal-mean WHP + 30% historical burn intersection count |
| Hurricane | NOAA HURDAT2 | 2015-2024 | Wind-speed-squared-weighted track point proximity, 150mi linear decay |
| Drought | U.S. Drought Monitor county statistics | 2015-2024 | Average % time in D0-or-worse, area-weighted county -> ZCTA |
| Extreme Heat | gridMET daily max temp + min RH | 2015-2024 | 60% days >90F, 40% days heat index >100F (Rothfusz regression) |
| Seismic | USGS National Seismic Hazard Model (2018) + Volcanic Threat Assessment | latest model | 80% zonal-mean PGA + 20% distance-decayed volcano threat |
| Air Quality | CDC/EPA fused daily census-tract PM2.5 surface | 2016-2020 | Avg days/year with tract mean PM2.5 above 35.4 ug/m3 (AQI > 100) |

**WHP and the USGS seismic hazard model are point-in-time hazard models, not
event histories** -- they use the latest published model version rather than
a 2015-2024 rolling aggregation, since there's no annual time series to
aggregate.

**Winter Weather was rebuilt off NCEI Storm Events onto gridMET** after two
symptoms of the same underlying flaw surfaced: scores clustering around
Dallas with no physical basis, and cliff-like discontinuities at state
lines, sharpest in Nevada. NCEI Storm Events is a human-report database --
report density tracks population, observer-network coverage, and each NWS
forecast office's own reporting culture as much as it tracks actual winter
weather, and because NWS zones never cross a state line, any difference in
two states' reporting culture showed up as a hard edge exactly on the
border. A spatial-smoothing pass was tried first and reduced the visible
symptom, but the raw signal was never a measure of risk to begin with -- no
amount of smoothing fixes a data source, only the presentation of it.

`pipeline/winter_weather.py` now uses gridMET daily precipitation + max
temp (`pipeline/sources/gridmet.py`, the same source Extreme Heat already
uses): a day counts toward the average when it has at least 0.01in
liquid-equivalent precipitation (NWS's own "measurable precipitation"
threshold) and a max temperature at or below 32F -- max, not min, since min
temp is below freezing almost every winter night everywhere and barely
discriminates one place from another, while max temp at or below freezing
means the day never warmed above freezing at all. This is model+station-
blended physical measurement with zero human reporting involved, so both
symptoms disappear at the root, and it's a continuous ~4km grid rather than
zone polygons, so there's no zone boundary left for a state-line artifact
to form on -- unlike Air Quality's tract-line cliffs (a real granularity
artifact in an otherwise continuous value), this category no longer runs
`spatial_smooth` at all. Verified directly: the Nevada ZCTA pair that
originally motivated this (89883/84083) went from a 68-point gap to a
10-point one, and Dallas-metro ZCTAs now average within 1 point of
comparable-latitude rural West Texas ZCTAs.

This measures winter precipitation *frequency*, not snowfall *amount* --
SNODAS (NOAA/NOHRSC gridded snow depth/SWE) would be the more direct
measurement but ships as flat binary grids over FTP with no netCDF/
shapefile/CSV option, so it was set aside in favor of reusing gridMET's
already-proven ingestion path. Worth revisiting if snowfall amount
specifically is ever needed. `sources/ncei_storm_events.py` and
`sources/nws_zones.py` are unchanged and still used elsewhere -- Severe
Convective still uses NCEI's point-event path, and no other category used
NWS zones.

While rebuilding this category, a severe bug surfaced in the shared gridMET
ingestion pattern itself: indexing a netCDF4 `Variable` directly returns a
properly-scaled `numpy.ma.MaskedArray` (gridMET packs values as scaled
uint16 with a `_FillValue` for the ~40% of the CONUS grid that's ocean/
Canada/Mexico), but wrapping that in `np.array()` silently discards the
mask and returns the *raw, unscaled fill sentinel* for every masked cell
instead. This was present in the already-shipped `heat.py` too, inflating
its day-count thresholds at every ocean-adjacent coastal ZCTA (confirmed on
a real sample day: 502,251 false-positive cells vs. 175,320 correct once
fixed, a 2.9x inflation). Both `heat.py` and `winter_weather.py` now keep
values as masked arrays through the full comparison chain and only fill
masked cells to `False` at the very end; `heat.py` additionally has to
capture the mask *before* calling `rothfusz_heat_index()`, since that
function's internal `np.asarray()` would otherwise strip it right back off.
Heat's cached rasters were regenerated under the fix; coastal ZCTA heat
scores changed as a result.

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
The CDC/EPA fused surface blends those same monitors with EPA's
Downscaler model to give a daily value everywhere, so the layer is
measured-and-modelled instead of measured in cities and guessed
elsewhere. Being daily, it also preserves the "days above a threshold"
metric that a satellite annual-mean product would have forced us to
abandon.

**Air Quality apportions from census tracts, not counties.** An earlier
version of this category used CDC's county-level release of the same
Downscaler model. That data was never a human-report signal -- unlike
Winter Weather's old NCEI source, it's real monitor+model measurement --
but bucketing it to 3,109 counties, some spanning hundreds of km, created
a genuine granularity artifact: two ZCTAs a few miles apart on opposite
sides of a county line could land 60+ points apart from an otherwise
continuous field. CDC separately publishes the same Downscaler model at
census-tract granularity (95,072 tracts, ~30x finer), which shrinks that
artifact directly -- the largest neighbouring-ZCTA gap anywhere in the
country dropped to under 42 points, with zero pairs left above 60, once
apportionment moved to tracts. `scoring.spatial_smooth` still runs before
ranking (tract lines are a real, if now much smaller, administrative
boundary, unlike Winter Weather's zone lines, which were a fake signal
removed by changing data source rather than smoothing).

This category deliberately does **not** detrend against population
density the way Severe Convective does. Dense-urban PM2.5 elevation is a
real physical signal here -- traffic and industrial sources concentrate
where people do -- not a reporting-density artifact, so it's left
undamped. Confirmed directly: LA-metro ZCTAs average 94 vs. 77 for
comparably-latitude rural high desert nearby, and the fused surface's own
"days above threshold" field is used raw, never population-weighted.

Window is 2016-2020, narrower than the county release's 2015-2021: CDC's
tract-level Downscaler series doesn't extend as far as its county
release. Both 2020-vintage: the tract dataset's FIPS predate Connecticut's
2022 county-to-Planning-Region switch, and 2020 cartographic boundaries
are already period-correct for that, so no legacy-geography join fix
(needed for the old county-level source, see git history) is required
here.

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
-- fixed by showing 5 decimal places in this table specifically. 3 still
wasn't enough: hurricane has two ZCTAs in its top 25 that agree to 3
decimals and only separate at the 4th.

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
mail is delivered. Those areas get their own `NOZIP-{hash}` polygons
(never 5 digits, so they can never be confused with or searched as a real
ZIP -- the hash is a content-derived id, not a serial number; see
`subdivide_large_gaps._stable_gap_ids()` for why it has to be deterministic
from geometry rather than assigned by row order). They are real geometry,
so the category modules score them directly like any other polygon -- a
marsh island off Charleston gets its own hurricane and flood exposure
computed, not a placeholder. `fill_nozip_scores.py` runs afterwards purely
as a safety net, filling any polygon a category legitimately had no data
for (raster sources such as WHP have no value over open water) from a
shared-boundary-weighted mean of its neighbours.

Gap polygons are also clipped against open water for display
(`clip_gap_water.py`, Natural Earth 10m ocean + lakes) -- the land mask
they're derived from comes from Census county boundaries, not the
basemap's own OSM-derived coastline, so without this a gap area could
render as land-colored fill sitting on visible water. This is render-only:
it edits `zcta_geometries_render.parquet` after
`build_render_geometries.py`, never the analysis geometry a score is
computed against, and a gap polygon keeps its original id even where
clipping reshapes it into a MultiPolygon. A polygon left under
`WATER_CLIP_SLIVER_AREA_M2` (0.05 km^2, chosen against this project's own
"a ZCTA is a few pixels wide at CONUS zoom" render-visibility logic) is
dropped rather than kept as an unrenderable remnant. Real ZCTAs are never
touched by this step.

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
  EF-scale for tornadoes, magnitude for hail and wind. It has never been
  checked against the severe-weather literature, and it drives Severe
  Convective outright. (Winter Weather no longer uses this function or
  NCEI Storm Events at all -- see the gridMET rebuild above.) Deliberately
  deferred, not overlooked.
- **Small-ZCTA fidelity is improved but not perfect.** At a 25m
  simplification tolerance the sub-0.5 km^2 band still doesn't match the
  raw source exactly; a handful of single-building urban ZCTAs (10271 on
  Wall Street is ~87m across) remain the hardest cases. Their flood score,
  being share-of-area, is the most sensitive to it.
- **Air Quality covers 2016-2020**, everything else 2015-2024 -- CDC's
  tract-level PM2.5 release doesn't extend as far as its county-level
  one. The composite therefore blends a 5-year and a 10-year climatology.
- Deployment target (live hosting vs. local/demo-video) -- not yet decided.
- Vector tiles (MVT/PMTiles) are the next real performance step, now that
  gzip has taken the cheap win.
