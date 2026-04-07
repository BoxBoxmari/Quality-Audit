#!/usr/bin/env python3
"""Analyze remaining_22_evidence_pack.xlsx to extract structured information."""

import sys
from pathlib import Path

import pandas as pd

# Fix encoding for Windows console
if sys.platform == "win32":
    sys.stdout.reconfigure(encoding="utf-8")

project_root = Path(__file__).resolve().parent.parent
xlsx_path = project_root / "remaining_22_evidence_pack.xlsx"

if not xlsx_path.exists():
    print(f"ERROR: File not found: {xlsx_path}")
    sys.exit(1)

xls = pd.ExcelFile(str(xlsx_path))
df_map = pd.read_excel(xls, sheet_name="Mapping_22")

print("=== Summary by Reason Code ===")
summary = df_map.groupby("Reason Code").size()
for reason, count in summary.items():
    print(f"{reason}: {count}")

print("\n=== Sample table_ids per group ===")
for reason in df_map["Reason Code"].unique():
    sample_ids = df_map[df_map["Reason Code"] == reason]["table_id"].tolist()[:3]
    print(f"{reason}: {sample_ids}")

print("\n=== Full Mapping_22 DataFrame (first 5 rows) ===")
print(df_map.head(5).to_string())

# Extract key columns for analysis
key_cols = [
    "table_id",
    "Reason Code",
    "validator_type",
    "Status",
    "total_row_method",
    "quality_score",
]
if all(col in df_map.columns for col in key_cols):
    print("\n=== Key columns summary ===")
    print(df_map[key_cols].to_string())
