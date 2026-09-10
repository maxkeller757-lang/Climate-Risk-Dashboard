"""
Hurricane / Tropical category: FEMA National Risk Index Hurricane Expected
Annual Loss Rate - Building (HRCN_ALRB), a federally modeled per-census-
tract hazard measure (hurricane-force-wind event frequency x building
exposure x historical loss ratio), area-weighted onto ZCTAs -- same
tract-source-apportioned-to-ZCTA shape as air_quality.py.

Replaces an earlier version of this category built from NOAA HURDAT2
storm-track proximity (ZCTA-centroid distance to 6-hourly track points,
linear decay to 150mi). That approach needed two admittedly
not-data-derived corrections layered on top just to make the map read as
plausible (an S-curve contrast stretch and a coast-distance divisor, both
documented in the git history as hand-tuned constants, not fit to
anything) -- a sign the underlying model was too crude on its own. NRI's
per-tract loss modeling is accurate enough at its native ~10x-finer
geography that no such correction is needed here; see the FEMA NRI
technical documentation for its own methodology.

ALRB (a loss *rate*, i.e. normalized by exposure value) is used rather
than FEMA's blended HRCN_RISKS score, which multiplies loss by a Social
Vulnerability / Community Resilience adjustment -- every other category
in this project is a pure hazard-exposure measure with no socioeconomic
weighting, and ALRB keeps Hurricane consistent with that.

NRI leaves HRCN_ALRB null for tracts where it doesn't model hurricane
hazard at all, not just where data happens to be missing -- confirmed by
checking the actual distribution: entire inland/non-coastal states
(Colorado, Wyoming, Montana, Idaho, Utah, the Dakotas, Oregon,
Washington...) are 100% null, while hurricane-exposed states are
consistently ~99%+ covered. That's "hurricane risk here is zero", not "we
don't know" -- so unlike every other category's genuine small data gaps
(a marsh polygon WHP has no raster value over), these are filled with 0
directly rather than routed through fill_nozip_scores's neighbour
interpolation. That mechanism assumes gaps are sparse residue near real
data (its own docstring: "the residue"); ~15k ZCTAs spanning whole
contiguous states would instead disqualify themselves and their
neighbours as interpolation donors for every category simultaneously,
and likely leaves an unfillable region entirely (no real donor anywhere
nearby), tripping fill_nozip_scores's own "still missing after
interpolation" safety check.

Run: pixi run python pipeline/hurricane.py
"""
import geopandas as gpd

from config import ZCTA_GEOMETRIES_PATH
from scoring import percentile_rank, upsert_zip_scores, write_layer_geojson
from sources.census_tracts import load_tracts
from sources.fema_nri import load_hurricane_alrb
from spatial import area_weighted_average

CATEGORY = "hurricane"
COLOR = "#00707A"


def main():
    zcta = gpd.read_parquet(ZCTA_GEOMETRIES_PATH)
    tracts = load_tracts()

    print("Querying FEMA NRI Hurricane Expected Annual Loss Rate...")
    alrb = load_hurricane_alrb()

    covered = tracts["GEOID"].isin(alrb.index).mean()
    print(f"{len(alrb)} tracts with HRCN_ALRB; {100 * covered:.1f}% of CONUS tracts covered")

    raw = area_weighted_average(zcta, tracts, "GEOID", alrb)
    raw = raw.rename(columns={"value": "hurricane_alrb"})

    # NaN here means "no tract with a hurricane loss rate overlapped this
    # ZCTA at all" -- true for both real no-hazard geography (see module
    # docstring) and the rare offshore/marsh sliver with no tract overlap
    # whatsoever. Zero is the correct value for both: no modeled hurricane
    # building-loss rate is exactly "no hurricane exposure".
    filled = int(raw["hurricane_alrb"].isna().sum())
    if filled:
        print(f"{filled} ZCTA(s) had no hurricane-hazard tract overlap -- scored as zero exposure")
    raw["hurricane_alrb"] = raw["hurricane_alrb"].fillna(0.0)

    scored = percentile_rank(raw, raw_col="hurricane_alrb")

    upsert_zip_scores(CATEGORY, scored, raw_col="hurricane_alrb")
    write_layer_geojson(CATEGORY, COLOR)
    print(f"{CATEGORY}: done")


if __name__ == "__main__":
    main()
