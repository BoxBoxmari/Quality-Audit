"""
Phase 1.4: Báo cáo Phase 1 — table inventory + G1 list + FS coverage.

Reads results/table_inventory.csv, results/g1_list.csv, results/phase1_fs_coverage.csv;
writes a summary report to results/phase1_report.md.
"""

from __future__ import annotations

import csv
import sys
from collections import defaultdict
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
RESULTS_DIR = REPO_ROOT / "results"
INVENTORY_CSV = RESULTS_DIR / "table_inventory.csv"
G1_LIST_CSV = RESULTS_DIR / "g1_list.csv"
FS_COVERAGE_CSV = RESULTS_DIR / "phase1_fs_coverage.csv"
REPORT_MD = RESULTS_DIR / "phase1_report.md"


def main() -> int:
    if not INVENTORY_CSV.exists():
        print(f"Missing: {INVENTORY_CSV}", file=sys.stderr)
        return 1

    # --- Table inventory summary ---
    inv_by_file: dict[str, int] = defaultdict(int)
    inv_by_type: dict[str, int] = defaultdict(int)
    inv_by_status: dict[str, int] = defaultdict(int)
    total_rows = 0

    with open(INVENTORY_CSV, newline="", encoding="utf-8") as f:
        reader = csv.DictReader(f)
        for row in reader:
            total_rows += 1
            fn = (row.get("file_name") or "").strip()
            tt = (row.get("table_type") or "").strip() or "(blank)"
            st = (row.get("status_enum") or "").strip() or "(blank)"
            if fn:
                inv_by_file[fn] += 1
            inv_by_type[tt] += 1
            inv_by_status[st] += 1

    # --- G1 list summary ---
    g1_rows: list[dict[str, str]] = []
    if G1_LIST_CSV.exists():
        with open(G1_LIST_CSV, newline="", encoding="utf-8") as f:
            g1_rows = list(csv.DictReader(f))
    g1_by_file: dict[str, list[str]] = defaultdict(list)
    for row in g1_rows:
        fn = (row.get("file_name") or "").strip()
        tid = (row.get("table_id") or "").strip()
        if fn and tid:
            g1_by_file[fn].append(tid)

    # --- FS coverage ---
    fs_rows: list[dict[str, str]] = []
    if FS_COVERAGE_CSV.exists():
        with open(FS_COVERAGE_CSV, newline="", encoding="utf-8") as f:
            fs_rows = list(csv.DictReader(f))
    fs_ok = sum(1 for r in fs_rows if (r.get("all_three_ok") or "").strip() == "1")
    fs_missing: list[str] = [
        (r.get("file_name") or "").strip()
        for r in fs_rows
        if (r.get("all_three_ok") or "").strip() != "1"
    ]

    # --- Write report ---
    REPORT_MD.parent.mkdir(parents=True, exist_ok=True)
    lines = [
        "# Phase 1 Report — Quality Audit Gap Hunting",
        "",
        "## 1. Table Inventory Summary",
        "",
        f"- **Total rows**: {total_rows}",
        f"- **Files**: {len(inv_by_file)}",
        "",
        "### By file",
        "",
        "| file_name | tables |",
        "|-----------|--------|",
    ]
    for fn in sorted(inv_by_file):
        lines.append(f"| {fn} | {inv_by_file[fn]} |")

    lines.extend([
        "",
        "### By table_type",
        "",
        "| table_type | count |",
        "|------------|-------|",
    ])
    for tt in sorted(inv_by_type):
        lines.append(f"| {tt} | {inv_by_type[tt]} |")

    lines.extend([
        "",
        "### By status_enum",
        "",
        "| status_enum | count |",
        "|-------------|-------|",
    ])
    for st in sorted(inv_by_status):
        lines.append(f"| {st} | {inv_by_status[st]} |")

    lines.extend([
        "",
        "## 2. G1 List (GENERIC_NOTE/TAX_NOTE, PASS, assertions_count=0)",
        "",
        f"- **Total G1 tables**: {len(g1_rows)}",
        "",
        "### By file",
        "",
        "| file_name | count | table_ids |",
        "|-----------|-------|-----------|",
    ])
    for fn in sorted(g1_by_file):
        ids = g1_by_file[fn]
        ids_short = ", ".join(ids[:5]) + ("..." if len(ids) > 5 else "")
        lines.append(f"| {fn} | {len(ids)} | {ids_short} |")

    lines.extend([
        "",
        "## 3. G3 FS Coverage (B01/B02/B03 = BS/IS/CF)",
        "",
        f"- **Files with all three FS PASS + assertions**: {fs_ok} / {len(fs_rows)}",
        "",
    ])
    if fs_missing:
        lines.append("Files missing at least one of BS/IS/CF (PASS + assertions_count>0):")
        lines.append("")
        for fn in fs_missing:
            lines.append(f"- {fn}")
        lines.append("")
    lines.append("| file_name | has_BS | has_IS | has_CF | all_three_ok |")
    lines.append("|-----------|--------|--------|--------|--------------|")
    for r in fs_rows:
        fn = (r.get("file_name") or "").strip()
        bs = (r.get("has_BS") or "0").strip()
        iss = (r.get("has_IS") or "0").strip()
        cf = (r.get("has_CF") or "0").strip()
        ok = (r.get("all_three_ok") or "0").strip()
        lines.append(f"| {fn} | {bs} | {iss} | {cf} | {ok} |")

    lines.append("")
    REPORT_MD.write_text("\n".join(lines), encoding="utf-8")
    print(f"Phase 1 report -> {REPORT_MD}", file=sys.stderr)
    return 0


if __name__ == "__main__":
    sys.exit(main())
