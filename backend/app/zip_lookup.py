"""
USPS ZIP code -> ZCTA5 resolution.

Resolution order:

1. The crosswalk (data/zip_to_zcta.parquet, built by
   pipeline/build_zip_crosswalk.py). This is what handles the ZIPs that
   direct matching cannot: PO-box-only and large-volume-customer ZIPs have
   no land area of their own, so their code is never a ZCTA -- 78381
   (Rockport TX) lives inside ZCTA 78382. Roughly 7,100 ZIPs resolve only
   this way.
2. Direct numeric match, as a fallback. Most ZIPs are identical to their
   ZCTA, so this still covers a newly-issued ZIP the crosswalk hasn't
   caught up with yet.

A ZIP that resolves to a ZCTA outside this project's CONUS scope (Alaska,
Hawaii, Puerto Rico, territories) is reported separately from one that
simply doesn't exist -- "we don't cover that" and "that isn't a ZIP" are
different answers and the UI should be able to say which.
"""
from .data_access import load_zip_scores, load_zip_to_zcta


def classify_zip_format(zipcode: str) -> str | None:
    """None if `zipcode` is a valid 5-digit zip format; otherwise a short
    machine-readable reason code for exactly why it isn't, so callers can
    give a specific, correct error message instead of one generic
    "invalid" bucket. Order matters -- checks are ordered from broadest
    (empty) to narrowest (length) so each input gets its single most
    relevant reason."""
    if not zipcode:
        return "empty"
    if zipcode != zipcode.strip():
        return "whitespace"
    # isascii() first: str.isdigit() alone also accepts non-ASCII Unicode
    # decimal digits (e.g. full-width "１２３４５"),
    # which would otherwise pass this check and then just silently fail
    # the lookup, misreporting a malformed input as "well-formed but not
    # found" instead of "invalid format".
    if not zipcode.isascii() or not zipcode.isdigit():
        return "non_numeric"
    if len(zipcode) < 5:
        return "too_short"
    if len(zipcode) > 5:
        return "too_long"
    return None


def is_valid_zip_format(zipcode: str) -> bool:
    return classify_zip_format(zipcode) is None


def resolve_zcta(zipcode: str) -> tuple[str | None, str | None]:
    """Resolve a USPS ZIP to a scored ZCTA5.

    Returns (zcta5, None) on success, or (None, reason) where reason is
    one of:
      unknown_zip      -- not a US ZIP code we have any record of
      no_zcta          -- a real ZIP, but Census defines no ZCTA for it
                          (a handful of territory ZIPs)
      outside_conus    -- a real ZIP mapping to a real ZCTA, but outside
                          this project's CONUS-only scope
    """
    if not is_valid_zip_format(zipcode):
        return None, "unknown_zip"

    scored = set(load_zip_scores()["zcta5"])
    crosswalk = load_zip_to_zcta()

    row = crosswalk.get(zipcode)
    if row is None:
        # Not in the crosswalk at all. Fall back to a direct match so a
        # ZIP newer than the crosswalk file still works.
        if zipcode in scored:
            return zipcode, None
        return None, "unknown_zip"

    zcta = row["zcta5"]
    if zcta is None:
        return None, "no_zcta"
    if zcta not in scored:
        return None, "outside_conus"
    return zcta, None
