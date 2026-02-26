#!/usr/bin/env python3
"""Extract detailed evidence from remaining_22_evidence_pack.xlsx sheets."""
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

# Get all sheet names (excluding Mapping_22)
data_sheets = [s for s in xls.sheet_names if s != "Mapping_22"]

print("=== Extracting Evidence Details ===\n")

# Group by Reason Code for organized output
grouped = df_map.groupby("Reason Code")

for reason_code, group_df in grouped:
    print(f"\n{'='*80}")
    print(f"GROUP: {reason_code} ({len(group_df)} tables)")
    print(f"{'='*80}\n")

    for idx, row in group_df.iterrows():
        table_id = row.get("table_id", "unknown")
        validator_type = row.get("validator_type", "unknown")
        status = row.get("Status", "unknown")
        total_row_method = row.get("total_row_method", "N/A")
        quality_score = row.get("quality_score", "N/A")

        print(f"--- Table: {table_id} ---")
        print(f"  Validator: {validator_type} | Status: {status}")
        print(
            f"  Total Row Method: {total_row_method} | Quality Score: {quality_score}"
        )

        # Find matching sheet (Excel truncates to 31 chars)
        sheet_match = None
        for sheet_name in data_sheets:
            # Match by index number prefix (e.g., "09_", "19_")
            sheet_idx_str = str(idx + 1).zfill(2) + "_"
            if sheet_name.startswith(sheet_idx_str):
                sheet_match = sheet_name
                break

        if not sheet_match:
            print(f"  ⚠ Sheet not found for index {idx + 1}")
            continue

        try:
            df_sheet = pd.read_excel(xls, sheet_name=sheet_match)
            print(f"  ✓ Sheet: {sheet_match} | Shape: {df_sheet.shape}")

            # Try to identify sections:
            # 1. FS casting snapshot (usually starts with header row, has table data)
            # 2. Log excerpt (usually contains "INFO", "table_id", or log patterns)

            # Look for FS casting section (first non-empty rows with structured data)
            fs_start = None
            log_start = None

            for i in range(min(20, len(df_sheet))):
                row_data = df_sheet.iloc[i]
                row_str = " ".join(str(x).lower() for x in row_data if pd.notna(x))

                # FS casting usually has column headers or numeric data
                if fs_start is None and (
                    "column" in row_str
                    or any(
                        str(x)
                        .replace(",", "")
                        .replace("(", "-")
                        .replace(")", "")
                        .strip()
                        .isdigit()
                        for x in row_data
                        if pd.notna(x) and str(x).strip()
                    )
                ):
                    fs_start = i

                # Log excerpt usually contains log patterns
                if (
                    "info" in row_str
                    or "debug" in row_str
                    or "table_id" in row_str
                    or "total_row" in row_str
                ):
                    if log_start is None:
                        log_start = i
                    break

            if fs_start is not None:
                fs_end = log_start if log_start else min(fs_start + 30, len(df_sheet))
                print(f"\n  [FS Casting Snapshot: rows {fs_start}-{fs_end}]")
                fs_section = df_sheet.iloc[fs_start:fs_end]
                # Print first few rows of FS casting
                for r_idx in range(min(5, len(fs_section))):
                    row_vals = [
                        str(v)[:30] if pd.notna(v) else ""
                        for v in fs_section.iloc[r_idx]
                    ]
                    print(f"    Row {fs_start + r_idx}: {' | '.join(row_vals[:5])}")

            if log_start is not None:
                log_end = min(log_start + 35, len(df_sheet))
                print(f"\n  [Log Excerpt: rows {log_start}-{log_end}]")
                log_section = df_sheet.iloc[log_start:log_end]
                # Print key log lines
                for r_idx in range(min(10, len(log_section))):
                    row_vals = [
                        str(v) if pd.notna(v) else "" for v in log_section.iloc[r_idx]
                    ]
                    row_text = " ".join(row_vals).strip()
                    if row_text and len(row_text) > 10:
                        print(f"    {row_text[:150]}")

            print()  # Blank line between tables

        except Exception as e:
            print(f"  ✗ Error reading sheet {sheet_match}: {e}")
            continue

print("\n=== Extraction Complete ===")
