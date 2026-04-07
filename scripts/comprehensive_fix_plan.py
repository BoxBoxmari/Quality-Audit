#!/usr/bin/env python3
"""Comprehensive analysis and fix plan for all 22 remaining issues."""

import json
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

# Group by Reason Code
groups = defaultdict(list)
for idx, row in df_map.iterrows():
    reason = row.get("Reason Code", "UNKNOWN")
    groups[reason].append((idx, row))

print("=" * 80)
print("COMPREHENSIVE FIX PLAN: All 22 Remaining FAIL/WARN Issues")
print("=" * 80)
print(f"\nTotal Groups: {len(groups)}")
print(f"Total Issues: {len(df_map)}\n")

# Extract detailed evidence for each group
all_evidence = {}

for reason_code in sorted(groups.keys()):
    group_items = groups[reason_code]
    group_evidence = []

    for idx, row in group_items:
        table_id = row.get("table_id", "unknown")
        validator_type = row.get("validator_type", "unknown")
        status = row.get("Status", "unknown")
        total_row_method = row.get("total_row_method", "N/A")
        quality_score = row.get("quality_score", "N/A")
        extractor_engine = row.get("extractor_engine", "N/A")

        # Find sheet by index prefix
        sheet_idx_str = str(idx + 1).zfill(2) + "_"
        sheet_match = next(
            (s for s in xls.sheet_names if s.startswith(sheet_idx_str)), None
        )

        evidence_item = {
            "table_id": table_id,
            "validator_type": validator_type,
            "status": status,
            "total_row_method": total_row_method,
            "quality_score": quality_score,
            "extractor_engine": extractor_engine,
            "sheet_found": sheet_match is not None,
        }

        if sheet_match:
            try:
                df_sheet = pd.read_excel(xls, sheet_name=sheet_match)

                # Extract log lines (look for diagnostic info)
                log_lines = []
                fs_preview_rows = []

                for i in range(min(100, len(df_sheet))):
                    row_vals = [str(v) if pd.notna(v) else "" for v in df_sheet.iloc[i]]
                    row_text = " ".join(row_vals).strip()

                    # Log lines contain diagnostic keywords
                    if (
                        any(
                            kw in row_text.lower()
                            for kw in [
                                "info",
                                "debug",
                                "warn",
                                "fail",
                                "table_id",
                                "total_row",
                                "column",
                                "numeric",
                                "mismatch",
                                "sai lệch",
                                "tính lại",
                                "quality_score",
                                "extractor",
                                "amount_cols",
                                "chosen_numeric",
                            ]
                        )
                        and len(row_text) > 10
                    ):  # Filter out empty rows
                        log_lines.append(row_text[:300])

                    # FS preview (first few data rows, usually have numeric values)
                    if i < 15 and any(v.strip() for v in row_vals[:8]):
                        fs_preview_rows.append(
                            " | ".join(
                                [
                                    str(v)[:25] if pd.notna(v) else ""
                                    for v in row_vals[:8]
                                ]
                            )
                        )

                evidence_item["log_lines"] = log_lines[:10]  # Top 10 log lines
                evidence_item["fs_preview"] = fs_preview_rows[:5]  # Top 5 preview rows
                evidence_item["sheet_shape"] = (
                    f"{df_sheet.shape[0]} rows x {df_sheet.shape[1]} cols"
                )

            except Exception as e:
                evidence_item["error"] = str(e)

        group_evidence.append(evidence_item)

    all_evidence[reason_code] = {"count": len(group_items), "items": group_evidence}

# Print structured analysis
print("\n" + "=" * 80)
print("GROUP ANALYSIS BY REASON CODE")
print("=" * 80)

for reason_code in sorted(groups.keys()):
    group_data = all_evidence[reason_code]
    print(f"\n{'='*80}")
    print(f"GROUP: {reason_code} ({group_data['count']} tables)")
    print(f"{'='*80}\n")

    for item in group_data["items"]:
        print(f"  Table: {item['table_id']}")
        print(f"    Validator: {item['validator_type']} | Status: {item['status']}")
        print(f"    Total Row Method: {item['total_row_method']}")
        print(
            f"    Quality Score: {item['quality_score']} | Engine: {item['extractor_engine']}"
        )

        if item.get("sheet_found"):
            print(f"    Sheet Shape: {item.get('sheet_shape', 'N/A')}")

            if item.get("log_lines"):
                print(f"    Key Log Lines ({len(item['log_lines'])}):")
                for line in item["log_lines"][:5]:
                    print(f"      {line[:150]}")

            if item.get("fs_preview"):
                print("    FS Preview:")
                for preview in item["fs_preview"][:3]:
                    print(f"      {preview[:120]}")
        else:
            print("    ⚠ Sheet not found")

        print()

# Save structured evidence to JSON for programmatic access
evidence_json_path = project_root / "scripts" / "22_issues_evidence.json"
with open(evidence_json_path, "w", encoding="utf-8") as f:
    json.dump(all_evidence, f, indent=2, ensure_ascii=False)

print(f"\n{'='*80}")
print("Evidence saved to: scripts/22_issues_evidence.json")
print("=" * 80)
