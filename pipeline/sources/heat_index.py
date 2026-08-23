"""
NWS Rothfusz regression heat index, degrees Fahrenheit + % relative
humidity in, degrees Fahrenheit out. Standard formula plus NWS's published
low/high-humidity corner adjustments. Below 80F, NWS defines heat index as
just the air temperature (the regression isn't fit for that range).

Reference: https://www.wpc.ncep.noaa.gov/html/heatindex_equation.shtml
"""
import numpy as np


def rothfusz_heat_index(temp_f: np.ndarray, rh_pct: np.ndarray) -> np.ndarray:
    t, r = np.asarray(temp_f, dtype="float64"), np.asarray(rh_pct, dtype="float64")

    hi_simple = 0.5 * (t + 61.0 + (t - 68.0) * 1.2 + rh_pct * 0.094)
    hi_full = (
        -42.379 + 2.04901523 * t + 10.14333127 * r - 0.22475541 * t * r
        - 0.00683783 * t * t - 0.05481717 * r * r + 0.00122874 * t * t * r
        + 0.00085282 * t * r * r - 0.00000199788 * t * t * r * r
    )

    # Low-humidity adjustment: 80-112F, RH<13%. Clip before sqrt -- outside
    # that temp range the radicand can go negative; those rows are masked
    # out by apply_low below regardless, but an unclipped sqrt(negative)
    # still raises a RuntimeWarning for the wasted computation.
    low_rh_adj = ((13 - r) / 4) * np.sqrt(np.clip((17 - np.abs(t - 95.0)) / 17, 0, None))
    apply_low = (r < 13) & (t >= 80) & (t <= 112)

    # High-humidity adjustment: 80-87F, RH>85%
    high_rh_adj = ((r - 85) / 10) * ((87 - t) / 5)
    apply_high = (r > 85) & (t >= 80) & (t <= 87)

    hi = np.where(t < 80, hi_simple, hi_full)
    hi = np.where(apply_low, hi - low_rh_adj, hi)
    hi = np.where(apply_high, hi + high_rh_adj, hi)
    return hi
