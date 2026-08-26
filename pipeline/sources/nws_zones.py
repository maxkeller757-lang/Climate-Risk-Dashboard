"""
NCEI STATE_FIPS (numeric) -> USPS postal abbreviation lookup. Originally
built to join NOAA/NWS Public Forecast Zones (the geometry Winter
Weather's old NCEI-zone methodology apportioned onto ZCTAs, replaced by a
gridMET-based rebuild -- see README) against zone-keyed storm events. The
zone-loading/scoring code is gone; this mapping outlived it and is now
shared plumbing for anything that needs a CONUS+DC state-FIPS list, e.g.
census_tracts.py and subdivide_large_gaps.py.
"""

# CONUS + DC only, matching this project's scope.
FIPS_TO_POSTAL = {
    1: "AL", 4: "AZ", 5: "AR", 6: "CA", 8: "CO", 9: "CT", 10: "DE", 11: "DC",
    12: "FL", 13: "GA", 16: "ID", 17: "IL", 18: "IN", 19: "IA", 20: "KS",
    21: "KY", 22: "LA", 23: "ME", 24: "MD", 25: "MA", 26: "MI", 27: "MN",
    28: "MS", 29: "MO", 30: "MT", 31: "NE", 32: "NV", 33: "NH", 34: "NJ",
    35: "NM", 36: "NY", 37: "NC", 38: "ND", 39: "OH", 40: "OK", 41: "OR",
    42: "PA", 44: "RI", 45: "SC", 46: "SD", 47: "TN", 48: "TX", 49: "UT",
    50: "VT", 51: "VA", 53: "WA", 54: "WV", 55: "WI", 56: "WY",
}
