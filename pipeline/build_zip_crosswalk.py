"""
Build data/zip_to_zcta.parquet: a USPS ZIP -> ZCTA5 lookup for the API.

Most ZIPs are numerically identical to a ZCTA, which is why direct matching
got the dashboard this far. But two kinds never are:

  * PO-box-only and "large volume customer" ZIPs, which have no land area
    of their own at all (~9,200 of them) -- e.g. 78381 (Rockport TX) sits
    inside ZCTA 78382.
  * ZIPs whose numeric code simply isn't a ZCTA, because Census only
    creates a ZCTA where addresses cluster.

Both used to 404. This crosswalk resolves 7,135 ZIPs that direct matching
cannot.

Source: HRSA's ZIP Code to ZCTA Crosswalk. The obvious choice would have
been the UDS Mapper crosswalk this project originally planned for, but the
American Academy of Family Physicians sunset UDS Mapper in early 2024 and
its download is gone. HRSA publishes the same mapping, still maintained,
as a direct .xlsx with no auth.

Run: pixi run python pipeline/build_zip_crosswalk.py
"""
from pathlib import Path

import pandas as pd
import requests

from config import RAW_DIR, ZIP_TO_ZCTA_PATH

CROSSWALK_URL = (
    "https://data.hrsa.gov/DataDownload/GeoCareNavigator/"
    "ZIP%20Code%20to%20ZCTA%20Crosswalk.xlsx"
)


def _download() -> Path:
    RAW_DIR.mkdir(parents=True, exist_ok=True)
    path = RAW_DIR / "zip_zcta_crosswalk.xlsx"
    if not path.exists():
        print(f"Downloading {CROSSWALK_URL} ...")
        resp = requests.get(CROSSWALK_URL, timeout=180)
        resp.raise_for_status()
        path.write_bytes(resp.content)
    return path


def main():
    df = pd.read_excel(_download())

    df["zip5"] = df["ZIP_CODE"].astype(str).str.zfill(5)
    # `zcta` is float in the sheet (it carries NaN for the handful of
    # territory ZIPs that genuinely have no ZCTA), so round-trip through
    # int only for the rows that have a value.
    has_zcta = df["zcta"].notna()
    df.loc[has_zcta, "zcta5"] = (
        df.loc[has_zcta, "zcta"].astype(int).astype(str).str.zfill(5)
    )

    no_zcta = int((~has_zcta).sum())
    if no_zcta:
        print(f"{no_zcta} ZIP(s) have no ZCTA at all (territories) -- kept, mapped to null")

    out = df[["zip5", "zcta5", "ZIP_TYPE", "zip_join_type"]].rename(
        columns={"ZIP_TYPE": "zip_type", "zip_join_type": "join_type"}
    )
    # One exact-duplicate row exists upstream (42223, Fort Campbell TN).
    before = len(out)
    out = out.drop_duplicates(subset="zip5", keep="first").reset_index(drop=True)
    if len(out) != before:
        print(f"Dropped {before - len(out)} duplicate ZIP row(s)")

    ZIP_TO_ZCTA_PATH.parent.mkdir(parents=True, exist_ok=True)
    out.to_parquet(ZIP_TO_ZCTA_PATH)

    po_box = int(out["zip_type"].str.contains("Post Office", na=False).sum())
    print(f"Wrote {len(out)} ZIP -> ZCTA mappings to {ZIP_TO_ZCTA_PATH}")
    print(f"  {po_box} are PO-box / large-volume-customer ZIPs with no land area of their own")


if __name__ == "__main__":
    main()
