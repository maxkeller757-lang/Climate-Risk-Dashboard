"""
CDC/EPA fused-surface daily county PM2.5 (data.cdc.gov dataset 53mz-4zqd).

Chosen over EPA's monitor-based AQS summaries for coverage: AQS only has
monitors in 949 of 3,109 CONUS counties (31% of counties, 43% of land
area), so two-thirds of the map would have been interpolated from urban
monitor sites -- which would also have biased rural areas upward, since
monitors sit where pollution is. This product fuses those same monitor
observations with a CMAQ model surface to produce a daily value for
*every* county, so the layer is measured-and-modelled everywhere rather
than measured in cities and guessed elsewhere.

Daily values also mean the "days above a threshold" metric survives the
switch -- a satellite annual-mean product would have forced a change of
metric to yearly averages.

The 24.9M daily rows are never downloaded: Socrata aggregates
server-side, so we pull one small row per county per year.
"""
import pandas as pd
import requests

ENDPOINT = "https://data.cdc.gov/resource/53mz-4zqd.json"

# Daily mean PM2.5 above this counts as an exceedance day. 35.4 ug/m^3 is
# the top of the EPA 24-hour "Moderate" band -- above it the AQI exceeds
# 100 and enters "Unhealthy for Sensitive Groups", the standard public
# -health trigger point.
PM25_THRESHOLD = 35.4

# The dataset ends 31 Oct 2022, so 2022 is a partial year and would
# undercount (PM2.5 exceedances are year-round: summer wildfire smoke,
# winter wood smoke and inversions). Use whole years only.
FIRST_YEAR = 2015
LAST_YEAR = 2021

# County mean, not the population-weighted field the dataset also offers:
# this is a hazard-of-place score, and population weighting would quietly
# reintroduce the same population bias that severe_convective has to
# correct for.
VALUE_FIELD = "pm25_mean_pred"


def _geoid(state: pd.Series, county: pd.Series) -> pd.Series:
    return state.str.zfill(2) + county.str.zfill(3)


def _query(params: dict) -> pd.DataFrame:
    resp = requests.get(ENDPOINT, params=params, timeout=300)
    resp.raise_for_status()
    return pd.DataFrame(resp.json())


def load_exceedance_days() -> pd.Series:
    """Average days per year with county mean PM2.5 above PM25_THRESHOLD,
    indexed by 5-digit county GEOID. Counties that never exceed are 0 --
    a real zero, not missing data."""
    years = range(FIRST_YEAR, LAST_YEAR + 1)

    # Every county present in the window, so non-exceeding counties get a
    # real 0 rather than dropping out of the result entirely.
    all_counties = _query(
        {
            "$select": "statefips,countyfips",
            "$where": f"year>='{FIRST_YEAR}' AND year<='{LAST_YEAR}'",
            "$group": "statefips,countyfips",
            "$limit": 50000,
        }
    )
    counties = _geoid(all_counties["statefips"], all_counties["countyfips"])
    print(f"  {len(counties)} counties present {FIRST_YEAR}-{LAST_YEAR}")

    totals = pd.Series(0.0, index=counties.values)
    for year in years:
        hits = _query(
            {
                "$select": "statefips,countyfips,count(*) as days",
                "$where": f"year='{year}' AND {VALUE_FIELD} > {PM25_THRESHOLD}",
                "$group": "statefips,countyfips",
                "$limit": 50000,
            }
        )
        if hits.empty:
            print(f"  {year}: 0 counties exceeded")
            continue
        idx = _geoid(hits["statefips"], hits["countyfips"])
        totals = totals.add(
            pd.Series(hits["days"].astype(float).values, index=idx.values), fill_value=0
        )
        print(f"  {year}: {len(hits)} counties with >=1 exceedance day")

    n_years = len(list(years))
    result = (totals / n_years).rename("avg_exceedance_days")
    result.index.name = "GEOID"
    return result
