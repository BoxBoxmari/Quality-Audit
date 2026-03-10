"""
Phase 1.3: G3 — FS coverage (B01/B02/B03 = BS/IS/CF).

Reads results/table_inventory.csv, per file checks that FS_BALANCE_SHEET,
FS_INCOME_STATEMENT, FS_CASH_FLOW each have at least one row with status=PASS
and assertions_count > 0. Writes results/phase1_fs_coverage.csv.
"""

from __future__ import annotations

import csv
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
RESULTS_DIR = REPO_ROOT / "results"
INVENTORY_CSV = RESULTS_DIR / "table_inventory.csv"
FS_COVERAGE_CSV = RESULTS_DIR / "phase1_fs_coverage.csv"

FS_TYPES = {
    "FS_BALANCE_SHEET": "has_BS",
    "FS_INCOME_STATEMENT": "has_IS",
    "FS_CASH_FLOW": "has_CF",
}


def _parse_assertions_count(val: str) -> int:
    s = (val or "").strip()
    if not s:
        return 0
    try:
        return int(s)
    except ValueError:
        return 0


def main() -> int:
    if not INVENTORY_CSV.exists():
        print(f"Missing: {INVENTORY_CSV}", file=sys.stderr)
        return 1

    by_file: dict[str, dict[str, bool]] = {}

    with open(INVENTORY_CSV, newline="", encoding="utf-8") as f:
        reader = csv.DictReader(f)
        for row in reader:
            file_name = (row.get("file_name") or "").strip()
            table_type = (row.get("table_type") or "").strip()
            status = (row.get("status_enum") or "").strip()
            assertions = _parse_assertions_count(row.get("assertions_count") or "")
            if not file_name or table_type not in FS_TYPES:
                continue
            if status != "PASS" or assertions <= 0:
                continue
            key = FS_TYPES[table_type]
            if file_name not in by_file:
                by_file[file_name] = {"has_BS": False, "has_IS": False, "has_CF": False}
            by_file[file_name][key] = True

    rows = []
    for file_name in sorted(by_file):
        d = by_file[file_name]
        rows.append({
            "file_name": file_name,
            "has_BS": "1" if d["has_BS"] else "0",
            "has_IS": "1" if d["has_IS"] else "0",
            "has_CF": "1" if d["has_CF"] else "0",
            "all_three_ok": "1" if (d["has_BS"] and d["has_IS"] and d["has_CF"]) else "0",
        })

    FS_COVERAGE_CSV.parent.mkdir(parents=True, exist_ok=True)
    fieldnames = ["file_name", "has_BS", "has_IS", "has_CF", "all_three_ok"]
    with open(FS_COVERAGE_CSV, "w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=fieldnames)
        w.writeheader()
        w.writerows(rows)

    print(f"G3 FS coverage: {len(rows)} files -> {FS_COVERAGE_CSV}", file=sys.stderr)
    return 0


if __name__ == "__main__":
    sys.exit(main())
