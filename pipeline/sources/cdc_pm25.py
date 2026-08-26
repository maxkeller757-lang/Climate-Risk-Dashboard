"""
CDC/EPA fused-surface daily census-tract PM2.5 (data.cdc.gov dataset
96sd-hxdt, "Daily Census Tract-Level PM2.5 Concentrations, 2016-2020").

Chosen over EPA's monitor-based AQS summaries for coverage: AQS only has
monitors in 949 of 3,109 CONUS counties (31% of counties, 43% of land
area), so two-thirds of the map would have been interpolated from urban
monitor sites -- which would also have biased rural areas upward, since
monitors sit where pollution is. This product fuses those same monitor
observations with EPA's Downscaler model to produce a daily value for
*every* census tract, so the layer is measured-and-modelled everywhere
rather than measured in cities and guessed elsewhere.

Tract-level, not county-level: an earlier version of this module queried
CDC's county-level release of the same Downscaler model (53mz-4zqd). That
data is real (monitor+model fused, not a human-report signal), but
bucketing it to 3,109 counties -- some spanning hundreds of km -- created
a genuine granularity artifact: ZCTAs a few miles apart on opposite sides
of a county line could get very different scores from an otherwise
continuous physical field. CDC publishes the same Downscaler model at
~30x finer geography (95,072 census tracts), which shrinks that artifact
directly without changing what's measured or reintroducing anything
report-based.

Daily values mean the "days above a threshold" metric survives the
switch -- a satellite annual-mean product would have forced a change of
metric to yearly averages.

Window is narrower than the county release (2016-2020 vs 2015-2021):
CDC's tract-level Downscaler series doesn't extend as far as its county
release. Five whole years is still a stable climatology for this metric.

The rows are never downloaded in bulk: Socrata aggregates server-side, so
we pull one small row per tract per year.
"""
import pandas as pd
import requests

ENDPOINT = "https://data.cdc.gov/resource/96sd-hxdt.json"

# Daily mean PM2.5 above this counts as an exceedance day. 35.4 ug/m^3 is
# the top of the EPA 24-hour "Moderate" band -- above it the AQI exceeds
# 100 and enters "Unhealthy for Sensitive Groups", the standard public
# -health trigger point.
PM25_THRESHOLD = 35.4

FIRST_YEAR = 2016
LAST_YEAR = 2020

# Mean predicted concentration, not population-weighted: this is a
# hazard-of-place score, and population weighting would quietly
# reintroduce the same population bias that severe_convective has to
# correct for. Unlike severe weather reporting, dense-urban PM2.5 here is
# a real physical signal (traffic and industrial sources concentrate
# where people do) and should come through undamped, not detrended away.
VALUE_FIELD = "DS_PM_pred"


def _geoid(ctfips: pd.Series) -> pd.Series:
    # ctfips is not a 6-digit tract suffix -- it's the full state+county+
    # tract concatenation with the state's leading zero stripped (e.g.
    # "1019955702" for Alabama tract 01019955702). Zero-pad to the
    # standard 11-digit tract GEOID width; no need to separately combine
    # statefips/countyfips (confirmed against live API response).
    return ctfips.str.zfill(11)


def _query(params: dict) -> pd.DataFrame:
    resp = requests.get(ENDPOINT, params=params, timeout=300)
    resp.raise_for_status()
    return pd.DataFrame(resp.json())


def load_exceedance_days() -> pd.Series:
    """Average days per year with tract mean PM2.5 above PM25_THRESHOLD,
    indexed by 11-digit tract GEOID. Tracts that never exceed are 0 -- a
    real zero, not missing data."""
    years = range(FIRST_YEAR, LAST_YEAR + 1)

    # Every tract present in the window, so non-exceeding tracts get a
    # real 0 rather than dropping out of the result entirely.
    all_tracts = _query(
        {
            "$select": "ctfips",
            "$where": f"year>='{FIRST_YEAR}' AND year<='{LAST_YEAR}'",
            "$group": "ctfips",
            "$limit": 200000,
        }
    )
    tracts = _geoid(all_tracts["ctfips"])
    print(f"  {len(tracts)} tracts present {FIRST_YEAR}-{LAST_YEAR}")

    totals = pd.Series(0.0, index=tracts.values)
    for year in years:
        hits = _query(
            {
                "$select": "ctfips,count(*) as days",
                "$where": f"year='{year}' AND {VALUE_FIELD} > {PM25_THRESHOLD}",
                "$group": "ctfips",
                "$limit": 200000,
            }
        )
        if hits.empty:
            print(f"  {year}: 0 tracts exceeded")
            continue
        idx = _geoid(hits["ctfips"])
        totals = totals.add(
            pd.Series(hits["days"].astype(float).values, index=idx.values), fill_value=0
        )
        print(f"  {year}: {len(hits)} tracts with >=1 exceedance day")

    n_years = len(list(years))
    result = (totals / n_years).rename("avg_exceedance_days")
    result.index.name = "GEOID"
    return result
