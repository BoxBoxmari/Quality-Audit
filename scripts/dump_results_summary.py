#!/usr/bin/env python
"""Dump summary data from results/*.xlsx to CSV and JSON for A2–A6 acceptance checks.

Reads sheet 'Tổng hợp kiểm tra' from each XLSX; outputs columns: Tên bảng,
Trạng thái kiểm tra, Status Enum, Status Category, Rule ID, Validator Type,
Extractor Engine, Quality Score, Failure Reason Code (and any extra columns present).

Usage:
  python scripts/dump_results_summary.py [--out-dir OUT] [--merge]
  Default OUT = results/dump ; --merge adds merged CSV/JSON of all files.
"""

import argparse
import json
import sys
from pathlib import Path

# Force UTF-8 for Windows
if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8")

import pandas as pd  # noqa: E402

# Summary columns used for A2–A6 (Acceptance Criteria)
SUMMARY_COLUMNS = [
    "Tên bảng",
    "Trạng thái kiểm tra",
    "Status Enum",
    "Status Category",
    "Rule ID",
    "Validator Type",
    "Extractor Engine",
    "Quality Score",
    "Failure Reason Code",
]


def find_summary_sheet(xl: pd.ExcelFile) -> str | None:
    for name in xl.sheet_names:
        s = str(name)
        if "Tổng hợp kiểm tra" in s or "Tong hop kiem tra" in s:
            return s
    for name in xl.sheet_names:
        s = str(name)
        if "summary" in s.lower() and "executive" not in s.lower():
            return s
    return None


def read_summary(path: Path) -> pd.DataFrame:
    xl = pd.ExcelFile(path, engine="openpyxl")
    sheet = find_summary_sheet(xl)
    if sheet is None:
        return pd.DataFrame()
    df = pd.read_excel(xl, sheet_name=sheet)
    df["_source_file"] = path.name
    return df


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Dump results/*.xlsx summary to CSV/JSON"
    )
    parser.add_argument(
        "--out-dir",
        type=Path,
        default=Path("results/dump"),
        help="Output directory for CSV/JSON (default: results/dump)",
    )
    parser.add_argument(
        "--merge",
        action="store_true",
        help="Also write merged summary CSV and JSON",
    )
    parser.add_argument(
        "--results-dir",
        type=Path,
        default=Path("results"),
        help="Directory containing *.xlsx (default: results)",
    )
    args = parser.parse_args()

    results_dir = args.results_dir.resolve()
    out_dir = args.out_dir.resolve()
    out_dir.mkdir(parents=True, exist_ok=True)

    xlsx_files = sorted(results_dir.glob("*.xlsx"))
    if not xlsx_files:
        print(f"No *.xlsx in {results_dir}", file=sys.stderr)
        sys.exit(1)

    all_dfs: list[pd.DataFrame] = []

    for path in xlsx_files:
        df = read_summary(path)
        if df.empty:
            print(f"Skip (no summary sheet): {path.name}", file=sys.stderr)
            continue
        # Select known columns + any extra; preserve order
        cols = [c for c in SUMMARY_COLUMNS if c in df.columns]
        extra = [
            c
            for c in df.columns
            if c not in SUMMARY_COLUMNS and not str(c).startswith("_")
        ]
        use = cols + extra + ["_source_file"]
        use = [c for c in use if c in df.columns]
        df = df[use]

        stem = path.stem
        csv_path = out_dir / f"{stem}_summary.csv"
        json_path = out_dir / f"{stem}_summary.json"
        df.to_csv(csv_path, index=False, encoding="utf-8-sig")
        records = df.replace({pd.NA: None}).to_dict(orient="records")
        with open(json_path, "w", encoding="utf-8") as f:
            json.dump(records, f, ensure_ascii=False, indent=2)
        print(f"Wrote {csv_path.name} and {json_path.name}")
        all_dfs.append(df)

    if args.merge and all_dfs:
        merged = pd.concat(all_dfs, ignore_index=True)
        merged.to_csv(out_dir / "merged_summary.csv", index=False, encoding="utf-8-sig")
        with open(out_dir / "merged_summary.json", "w", encoding="utf-8") as f:
            json.dump(
                merged.replace({pd.NA: None}).to_dict(orient="records"),
                f,
                ensure_ascii=False,
                indent=2,
            )
        print(f"Wrote merged_summary.csv and merged_summary.json in {out_dir}")


if __name__ == "__main__":
    main()
