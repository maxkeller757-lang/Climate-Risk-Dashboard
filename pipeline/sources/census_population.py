"""
County population estimates from the Census Population Estimates Program
(no API key required -- unlike api.census.gov, which now requires one for
even a single-request pull; this uses the bulk flat-file mirror instead).
"""
import pandas as pd
import requests

from config import RAW_DIR

POP_URL = (
    "https://www2.census.gov/programs-surveys/popest/datasets/2020-2024/"
    "counties/totals/co-est2024-alldata.csv"
)


def load_county_population() -> pd.Series:
    """Latest (2024) county population estimate, indexed by 5-digit county
    GEOID (STATE FIPS + COUNTY FIPS)."""
    path = RAW_DIR / "co-est2024-alldata.csv"
    if not path.exists():
        RAW_DIR.mkdir(parents=True, exist_ok=True)
        print(f"Downloading {POP_URL} ...")
        resp = requests.get(POP_URL, timeout=60)
        resp.raise_for_status()
        path.write_bytes(resp.content)

    df = pd.read_csv(path, encoding="latin1")
    df = df[df["COUNTY"] != 0]  # drop state-level summary rows
    geoid = df["STATE"].astype(str).str.zfill(2) + df["COUNTY"].astype(str).str.zfill(3)
    return pd.Series(df["POPESTIMATE2024"].values, index=geoid, name="population")
