#!/usr/bin/env python3
"""Detailed analysis of remaining_22_evidence_pack.xlsx - extract FS casting and log excerpts."""
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

# Read mapping sheet
df_map = pd.read_excel(xls, sheet_name="Mapping_22")

print("=== Detailed Analysis by Group ===\n")

# Group by Reason Code
for reason_code in sorted(df_map["Reason Code"].unique()):
    group_df = df_map[df_map["Reason Code"] == reason_code]
    print(f"\n{'='*80}")
    print(f"GROUP: {reason_code} ({len(group_df)} tables)")
    print(f"{'='*80}")

    for idx, row in group_df.iterrows():
        table_id = row.get("table_id", "unknown")
        validator_type = row.get("validator_type", "unknown")
        status = row.get("Status", "unknown")
        total_row_method = row.get("total_row_method", "N/A")
        quality_score = row.get("quality_score", "N/A")

        print(f"\n--- Table: {table_id} ---")
        print(f"  Validator: {validator_type}")
        print(f"  Status: {status}")
        print(f"  Total Row Method: {total_row_method}")
        print(f"  Quality Score: {quality_score}")

        # Try to read the individual sheet for this table
        sheet_name = (
            str(idx + 1).zfill(2) + "_" + table_id.replace("/", "_").replace("\\", "_")
        )
        # Also try alternative naming patterns
        alt_names = [
            table_id,
            f"tbl_{table_id.split('_')[-1]}" if "_" in table_id else table_id,
        ]

        sheet_found = False
        for sheet_candidate in [sheet_name] + alt_names:
            if sheet_candidate in xls.sheet_names:
                try:
                    df_sheet = pd.read_excel(xls, sheet_name=sheet_candidate)
                    print(f"  ✓ Found sheet: {sheet_candidate}")
                    print(f"    Shape: {df_sheet.shape}")

                    # Try to identify FS casting section (usually has header row)
                    # and log.txt section (usually starts with "INFO" or contains "table_id")
                    if len(df_sheet) > 0:
                        # Print first few rows to see structure
                        print("    First 3 rows preview:")
                        print(df_sheet.head(3).to_string(max_colwidth=50))
                    sheet_found = True
                    break
                except Exception:
                    continue

        if not sheet_found:
            print(f"  ⚠ Sheet not found (tried: {sheet_name}, {alt_names})")

print("\n\n=== Summary Statistics ===")
print(f"Total tables: {len(df_map)}")
print("\nBy Reason Code:")
summary = df_map.groupby("Reason Code").size()
for reason, count in summary.items():
    print(f"  {reason}: {count}")

print("\nBy Validator Type:")
validator_summary = df_map.groupby("validator_type").size()
for validator, count in validator_summary.items():
    print(f"  {validator}: {count}")

print("\nBy Status:")
status_summary = df_map.groupby("Status").size()
for status, count in status_summary.items():
    print(f"  {status}: {count}")
