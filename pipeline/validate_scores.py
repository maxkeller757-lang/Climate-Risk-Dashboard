"""
Phase 8 pipeline validation: spot-check known high/low-risk ZCTAs against
well-established regional risk patterns. A result that contradicts common
knowledge (e.g. Miami scoring low on hurricane risk) signals a bug in the
join or normalization, not a genuine surprise -- this is a sanity check,
not a source of truth.

Run: pixi run python pipeline/validate_scores.py
"""
import pandas as pd

from config import ZIP_SCORES_PATH

# (zcta5, label, category, expect "high" (>=60) or "low" (<=40))
CHECKS = [
    ("73160", "Moore OK -- tornado alley", "severe_convective", "high"),
    ("79015", "Pampa TX panhandle", "severe_convective", "high"),
    ("33139", "Miami Beach FL", "hurricane", "high"),
    ("70112", "New Orleans LA", "hurricane", "high"),
    ("80202", "Denver CO -- no hurricane exposure", "hurricane", "low"),
    ("14201", "Buffalo NY -- lake-effect snow", "winter_weather", "high"),
    ("33101", "Miami FL -- no winter weather", "winter_weather", "low"),
    ("98104", "Seattle WA -- Cascadia subduction zone", "seismic", "high"),
    ("33101", "Miami FL -- stable craton", "seismic", "low"),
    ("85003", "Phoenix AZ -- desert Southwest", "drought", "high"),
    ("85003", "Phoenix AZ -- desert Southwest", "heat", "high"),
    ("93725", "Fresno CA -- San Joaquin Valley, worst PM2.5 in CONUS", "air_quality", "high"),
    ("59802", "Missoula MT -- wildfire smoke + winter inversions", "air_quality", "high"),
    ("33139", "Miami Beach FL -- coastal, well ventilated", "air_quality", "low"),
    ("04101", "Portland ME -- coastal, well ventilated", "air_quality", "low"),
    ("70117", "Lower 9th Ward, New Orleans -- below sea level", "flood", "high"),
    ("33139", "Miami Beach FL -- barrier island", "flood", "high"),
]


def main():
    table = pd.read_parquet(ZIP_SCORES_PATH)
    table["zcta5"] = table["zcta5"].astype(str)

    failures = []
    for zcta, label, category, expect in CHECKS:
        score_col = f"{category}_score"
        if score_col not in table.columns:
            print(f"SKIP  {label:55s} {category:20s} (not scored yet)")
            continue
        row = table.loc[table["zcta5"] == zcta]
        if row.empty:
            print(f"SKIP  {label:55s} {category:20s} (ZCTA {zcta} not found)")
            continue
        score = row.iloc[0][score_col]
        ok = (score >= 60) if expect == "high" else (score <= 40)
        status = "PASS" if ok else "FAIL"
        if not ok:
            failures.append((label, category, score, expect))
        print(f"{status}  {label:55s} {category:20s} score={score:5.1f} (expect {expect})")

    if failures:
        print(f"\n{len(failures)} check(s) contradict known regional patterns -- investigate.")
    else:
        print("\nAll spot-checks consistent with known regional risk patterns.")


if __name__ == "__main__":
    main()
