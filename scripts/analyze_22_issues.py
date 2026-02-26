#!/usr/bin/env python3
"""Deep analysis of 22 remaining issues with actionable fix recommendations."""
import sys
from collections import defaultdict
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
data_sheets = {s: s for s in xls.sheet_names if s != "Mapping_22"}

# Group by Reason Code
groups = defaultdict(list)
for idx, row in df_map.iterrows():
    reason = row.get("Reason Code", "UNKNOWN")
    groups[reason].append((idx, row))

print("=== IMMEDIATELY PLAN: Fix All 22 Remaining FAIL/WARN ===\n")

for reason_code in sorted(groups.keys()):
    group_items = groups[reason_code]
    print(f"\n{'='*80}")
    print(f"GROUP {len(groups)}: {reason_code} ({len(group_items)} tables)")
    print(f"{'='*80}\n")

    for idx, row in group_items:
        table_id = row.get("table_id", "unknown")
        validator_type = row.get("validator_type", "unknown")
        status = row.get("Status", "unknown")
        total_row_method = row.get("total_row_method", "N/A")
        quality_score = row.get("quality_score", "N/A")

        # Find sheet
        sheet_idx_str = str(idx + 1).zfill(2) + "_"
        sheet_match = next(
            (s for s in data_sheets if s.startswith(sheet_idx_str)), None
        )

        if not sheet_match:
            print(f"  ⚠ {table_id}: Sheet not found")
            continue

        try:
            df_sheet = pd.read_excel(xls, sheet_name=sheet_match)

            # Extract log excerpt (usually contains diagnostic info)
            log_lines = []
            for i in range(min(50, len(df_sheet))):
                row_vals = [str(v) if pd.notna(v) else "" for v in df_sheet.iloc[i]]
                row_text = " ".join(row_vals).strip()
                if any(
                    keyword in row_text.lower()
                    for keyword in [
                        "info",
                        "debug",
                        "table_id",
                        "total_row",
                        "column",
                        "numeric",
                        "mismatch",
                        "sai lệch",
                        "tính lại",
                    ]
                ):
                    log_lines.append(row_text[:200])

            # Extract FS casting preview (first few data rows)
            fs_preview = []
            for i in range(min(10, len(df_sheet))):
                row_vals = [
                    str(v)[:20] if pd.notna(v) else "" for v in df_sheet.iloc[i]
                ]
                if any(v.strip() for v in row_vals):
                    fs_preview.append(" | ".join(row_vals[:6]))

            print(f"\n  Table: {table_id}")
            print(f"    Validator: {validator_type} | Status: {status}")
            print(
                f"    Total Row Method: {total_row_method} | Quality: {quality_score}"
            )
            print(
                f"    Sheet: {sheet_match} ({df_sheet.shape[0]} rows, {df_sheet.shape[1]} cols)"
            )

            # Print key log lines
            if log_lines:
                print("    Key Log Lines:")
                for line in log_lines[:5]:
                    print(f"      {line}")

            # Print FS preview
            if fs_preview:
                print("    FS Casting Preview:")
                for preview in fs_preview[:3]:
                    print(f"      {preview}")

        except Exception as e:
            print(f"  ✗ {table_id}: Error - {e}")

print("\n\n=== ANALYSIS COMPLETE ===")
