# Zip-Code Climate & Hazard Risk Dashboard

A map that scores every US zip code 0-100 across 9 hazard categories
(severe convective weather, flood, wildfire, hurricane, winter weather,
drought, extreme heat, seismic, air quality) plus a composite score,
using real historical hazard data (mostly 2015-2024) run through an
offline GIS pipeline.

**Status**: all 9 categories + composite are live, CONUS-wide (~40,000
polygons). Map, zip search, click-to-inspect, and the methodology modal
all work end-to-end against real pre-computed data.

**Desktop only** The layout isn't built for narrow/phone-width
screens; panels overlap below about 500px wide.

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
# Requires pixi itself already installed (https://pixi.sh) -- everything
# below assumes `pixi` is on PATH. pixi.lock is committed and pinned to
# win-64, so `pixi install` reproduces the exact same Python + Node
# environment on any Windows machine.

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
cd frontend
pixi run --manifest-path ../pixi.toml npm install   # one-time
pixi run --manifest-path ../pixi.toml npm run dev
```

## Data sources & methodology

Every score is a 0-100 percentile rank of a raw metric, computed once
offline and never recomputed at request time -- that's what makes 9
categories with wildly different raw units (event counts, % area,
days/year) comparable on one scale.

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

WHP and the USGS seismic model are point-in-time model outputs, not event
histories, so they use the latest published version instead of a rolling
2015-2024 window.

**Winter Weather was rebuilt off NCEI Storm Events onto gridMET.** The
old scores clustered oddly around Dallas and had hard cliffs at state
lines (worst in Nevada) -- both symptoms of the same root cause. NCEI
Storm Events is a human-report database, and report density tracks
population and each NWS office's own reporting habits as much as it
tracks actual winter weather; since NWS zones never cross a state line,
any difference in two states' reporting culture became a hard edge right
at the border. `winter_weather.py` now uses gridMET instead: a day counts
if it has at least 0.01in of precipitation and a max temp at or below
32F (max, not min -- min temp is below freezing almost every winter night
everywhere and doesn't discriminate). That's model+station-blended
physical measurement with no human reporting involved, so both symptoms
disappear at the root, and a continuous grid has no zone boundary for a
state-line artifact to form on in the first place. The Nevada ZCTA pair
that motivated this went from a 68-point gap to 10; Dallas now scores
within 1 point of comparable rural West Texas. It measures precipitation
*frequency*, not snowfall amount -- SNODAS would be more direct but ships
as flat binary FTP grids with no easy ingestion path, so gridMET (already
proven out by Heat) was the pragmatic choice.

Building this also surfaced a real bug in the shared gridMET ingestion
pattern: reading a masked netCDF4 variable as plain `np.array()` silently
discards the mask and returns garbage fill values for the ~40% of the
grid that's ocean/Canada/Mexico. This was already live in `heat.py`,
inflating its day-counts at every coastal ZCTA (2.9x too many flagged
cells on a sample day). Fixed in both files by keeping values masked
through the full comparison chain; heat's cached rasters were regenerated
and coastal scores changed as a result.

**Severe Convective is detrended against population density.** NCEI
report density tracks population as much as real storm activity, so
every major metro looked like a hazard hotspot before this fix.
`population_bias_correct` fits `log1p(severity) ~ log1p(density)` and
ranks the residual instead of the raw count, a standard technique in
severe-weather bias-correction literature. It doesn't fully remove
reporting bias -- rural areas can still underreport -- but it removes the
population-driven trend, which was the dominant, correctable piece.

**Extreme Heat uses gridMET for both sub-metrics**, not gridMET +
nClimGrid-Daily as originally scoped, since both need daily max temp
anyway and pulling two redundant 10-year grids wasn't worth it. The
Rothfusz heat-index regression was checked against NWS's published chart
before the full run, which caught a transcription bug (one coefficient
off by 1000x) that would have silently produced nonsense.

**Seismic's volcano component** is a small hand-curated table of CONUS
Cascades/Yellowstone/Long Valley centers from USGS's 2018 Volcanic Threat
Assessment -- USGS's own GIS product for this ships only as a detailed
ArcGIS Pro layer, overkill for "is this ZCTA near an active volcano."

**Severity weighting** (`ncei_storm_events.py`) is a v1 heuristic
(EF-scale/magnitude where available, deaths/injuries otherwise) that's
never been checked against the severe-weather literature, and it drives
Severe Convective outright. Worth revisiting before treating scores as
authoritative.

**Air Quality uses a fused monitor+model surface, apportioned by census
tract.** EPA's raw AQS monitors cover only 31% of CONUS counties and are
sited in cities, so using them directly would have interpolated most of
the map and biased rural air upward. The CDC/EPA fused surface (EPA's
Downscaler model) covers every tract, daily, instead. An earlier version
apportioned from counties -- real, non-report data, but bucketed to
3,109 counties, some spanning hundreds of km -- which created a genuine
granularity artifact: two ZCTAs a few miles apart on opposite sides of a
county line could land 60+ points apart from an otherwise continuous
field. Switching to tract-level apportionment (~30x finer) dropped the
worst neighboring-ZCTA gap to under 42, with none left above 60. Unlike
Severe Convective, this category deliberately does *not* detrend against
population density -- dense-urban PM2.5 elevation is a real physical
signal (traffic, industry), not a reporting artifact, so it's left
undamped (LA-metro ZCTAs average 94 vs. 77 for nearby rural high desert).
Window is 2016-2020, shorter than other categories, because CDC's
tract-level release doesn't extend as far as its county-level one.

**Composite score** is a weighted power-mean (exponent 3) of the 9
category percentiles, not a plain average -- weights and exponent live in
`pipeline/composite_weights.json`, so retuning either is a config change.
A plain average let places with several 90s (e.g. Miami Beach: Flood 99,
Hurricane 96) get dragged down by unrelated low categories; raising each
score to a power before averaging lets already-high scores dominate
(Miami Beach composites to 80 now, not 23). Drought, Seismic, and Air
Quality carry a lighter weight (0.05 vs. 0.15 for the rest): Drought
overlaps heavily with Wildfire/Heat's own signal, Seismic is a
comparatively rare and localized threat nationally, and Air Quality is
chronic exposure rather than acute-event risk. Hurricane is additionally
scaled by 0.9, since its own contrast stretch (see the table above)
would otherwise get amplified a second time by the power-mean.

**Zip -> ZCTA mapping.** Most zip codes numerically match a ZCTA5 code
directly, but ~9,200 PO-box-only and large-volume zips have no land area
of their own and aren't ZCTAs -- 78381 (Rockport, TX) sits inside ZCTA
78382, for example. A crosswalk (`build_zip_crosswalk.py` ->
`zip_to_zcta.parquet`) resolves 7,135 zips that direct matching can't;
direct matching still runs first as a fallback so newer zips still work.
The detail panel shows both codes when they differ. (UDS Mapper was the
obvious source for this crosswalk, but AAFP sunset it in 2024; HRSA
publishes the same mapping, still maintained, as a plain .xlsx.)

Zip lookups distinguish three failure modes instead of one generic "not
found": `unknown_zip` (not a real zip), `no_zcta` (real zip, but Census
defines no ZCTA for it -- mostly territories), and `outside_conus` (real
zip and ZCTA, just outside this project's scope, e.g. Honolulu).

## ZCTA geometry fixes

TIGER's raw ZCTA5 polygons, simplified naively, produce slivers and
overlaps at every shared boundary (adjacent edges drift apart
independently) and don't cover all of CONUS land (some low-population
areas have no assigned ZCTA at all). `fetch_zcta_geometries.py` fixes
both: topology-aware simplification via `GeoSeries.simplify_coverage()`,
so shared edges stay shared, and a gap-fill pass that merges any
uncovered land into its nearest ZCTA by boundary distance.

## The bottom-right panel

Two views share this panel, and which one shows depends on what the user
did most recently: click a **polygon** and you get its full category
breakdown; pick a **layer** and you get a table of the top 3 riskiest zip
codes for that hazard. Those ask different questions -- "what's it like
*here*" vs. "where's this worst" -- so one selection can't answer the
other. The table skips no-ZIP gap areas: they carry real scores, but
"three unnamed patches of national forest" doesn't help anyone, and on
some layers they're numerous enough near the top to crowd out every real
zip code.

Ranking: score descending, then apportioned population, then zip
ascending. Real ties happen wherever the raw metric hits a hard ceiling
(21 ZCTAs sit at 100% flood-zone coverage, 25 at Air Quality's day-count
cap) -- population is the tiebreak that means something there. The table
shows 5 decimal places rather than the usual 1, since a few near-top
ZCTAs only diverge past the 3rd or 4th decimal and would otherwise look
like ties. Each row also carries a county name (dominant-area overlay
against Census county polygons), so a result reads as "Miami-Dade
County, FL" instead of a bare zip code.

## No-ZIP land areas

Not all CONUS land has a ZIP code -- tidal marsh, barrier islands, and
unaddressed parcels get their own `NOZIP-{hash}` polygons instead (never
5 digits, so they can't be confused with or searched as a real zip; the
hash is content-derived and deterministic, not a serial number). These
are real geometry and get scored like any other polygon -- a marsh
island off Charleston gets its own real hurricane and flood exposure,
not a placeholder. `fill_nozip_scores.py` only steps in when a category
legitimately has no data for a polygon (a raster source like WHP has no
value over open water), filling it from a boundary-weighted average of
neighbors.

A handful of cleanup passes run on this gap-polygon set before scoring,
each one fixing a different problem found along the way:

- **Water clipping** (`clip_gap_water.py`) trims gap polygons against
  real coastline (Natural Earth 10m ocean + lakes), since the Census
  county land mask they're derived from doesn't match the basemap's own
  coastline -- render-only, never touches scores or analysis geometry.
  Slivers under 0.05 km^2 left behind get dropped rather than kept as
  unrenderable specks.
- **Exclusion list** (`excluded_gap_ids.csv`, `remove_excluded_gaps.py`)
  drops gap polygons that survive water-clipping but turned out to
  expose real scoring bugs rather than being cosmetic noise. Two
  separate root causes surfaced this way: `spatial_smooth` (used by Air
  Quality) finds neighbors across the *entire* geometry set, gap
  polygons included, so a single sliver with a bad tract-level PM2.5
  read could spread that value to every other sliver touching it; and
  `population_bias_correct` (used by Severe Convective) gives a
  near-zero-population sliver an artificially low "expected" baseline,
  so any real regional storm history nearby reads as an extreme outlier.
  Both were caught the same way -- comparing a gap polygon's score
  against its real-ZCTA neighbors' mean, flagging anything more than 25
  points over -- and confirmed safe to remove by checking the resulting
  hole stays under `verify_layers.py`'s 25 km^2 limit. This runs before
  every category module on a full rebuild, so excluded polygons are
  never scored at all. 409 excluded so far, across several rounds as
  more were found (roughly half from an automated detector, the rest
  from direct review).
- **Merging** (`merge_gaps_into_zcta.py`) handles gap polygons too big to
  just delete (up to ~63 km^2) that turned out to carry corrupted data of
  their own. Their area gets unioned into an adjacent real ZCTA's
  geometry instead of dropped, so there's no hole; the absorbing ZCTA's
  score is left completely untouched, only its geometry grows.
- **Vertex fixes** (`fix_zcta_geometry_defects.py`) patch individual bad
  vertices in *real* ZCTAs (not gap polygons) left over from raw TIGER
  digitization errors -- e.g. ZCTA 55605 (Grand Portage, MN) had a vertex
  28km out into Lake Superior, dragging a wedge of open water into the
  polygon. Fixed by removing the offending vertices and reconnecting the
  ring to points already there (no new points invented), keyed on exact
  coordinates rather than a "remove the southernmost point" heuristic --
  a future TIGER update could reshape the ZCTA enough that a heuristic
  starts deleting the wrong vertex instead.

## Map rendering

Basemap is a trimmed OpenFreeMap "liberty" vector style (~19 of ~111
layers kept: interstates, park/forest/water/urban landuse) -- free, no
API key, no rate limit. `tippecanoe` isn't available in this Windows dev
environment, so category layers ship as simplified GeoJSON instead of
vector tiles (GDAL's `ogr2ogr`, already part of this environment, can
generate real MVT/MBTiles output as an alternative worth revisiting).

Render geometry is simplified separately from analysis geometry
(`build_render_geometries.py`), since scoring needs precision the
browser doesn't -- a ZCTA is a few pixels wide at CONUS zoom. Layers are
pre-gzipped at pipeline build time and served compressed to any client
that supports it (~40MB -> ~9.7MB per layer, about 24%). Compression
happens once at build, not per request: large files go out through
uvicorn's zero-copy file sending and never reach body-based middleware
like `GZipMiddleware` at all, and compressing 40MB live would cost
real blocking CPU on every layer switch. The next real performance step
would be vector tiles, which would fetch only the polygons in view
instead of the whole country on every layer switch.

Two rendering traps worth knowing about: `shapely.set_precision()` snaps
to a grid and *deletes* polygons smaller than it, rather than just
rounding their coordinates -- use the GeoJSON writer's
`COORDINATE_PRECISION` instead, which only formats output and leaves
geometry intact. And a polygon with a null score renders at the bottom
of the color ramp, visually identical to a hole -- `write_layer_geojson`
raises on any missing score or empty geometry rather than silently
filling it in. `pipeline/verify_layers.py` checks both, plus that the
polygons actually blanket CONUS land, and reports per-layer vertex count
and file size.

The map is bounded to CONUS + ~5deg padding (not the whole globe) and fit
to that box on load, so the initial view is always CONUS-centered
regardless of viewport aspect ratio.
