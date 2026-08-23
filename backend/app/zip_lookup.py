"""
USPS zip code -> ZCTA5 resolution.

v1 (current): most USPS zip codes are numerically identical to their ZCTA5
code (ZCTAs are built from the most common zip per census block), so we
resolve by direct match against the zip_scores table.

TODO (Phase 5 hardening, deferred per prototype-first pacing): direct match
does not cover PO-box-only zips or zips that split across multiple ZCTAs.
The intended fix is the free UDS Mapper ZIP-to-ZCTA crosswalk
(https://udsmapper.org/zip-code-to-zcta-crosswalk/), which explicitly maps
those edge cases to a real ZCTA. Until that's wired in, a zip with no direct
ZCTA match returns None and the API layer reports it as not found rather
than silently guessing.
"""
from .data_access import load_zip_scores


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


def resolve_zcta(zipcode: str) -> str | None:
    """Return the ZCTA5 code for a USPS zip, or None if unresolvable."""
    if not is_valid_zip_format(zipcode):
        return None
    scores = load_zip_scores()
    if zipcode in set(scores["zcta5"]):
        return zipcode
    return None
