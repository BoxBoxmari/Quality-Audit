"""
Phase 1.2: G1 list — GENERIC_NOTE/TAX_NOTE with status=PASS and assertions_count=0.

Reads results/table_inventory.csv, filters by table_type in (GENERIC_NOTE, TAX_NOTE),
status_enum=PASS, assertions_count=0, writes results/g1_list.csv.
"""

from __future__ import annotations

import csv
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
RESULTS_DIR = REPO_ROOT / "results"
INVENTORY_CSV = RESULTS_DIR / "table_inventory.csv"
G1_CSV = RESULTS_DIR / "g1_list.csv"

G1_TABLE_TYPES = {"GENERIC_NOTE", "TAX_NOTE"}


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

    g1_rows: list[dict[str, str]] = []
    with open(INVENTORY_CSV, newline="", encoding="utf-8") as f:
        reader = csv.DictReader(f)
        fieldnames = reader.fieldnames or []
        for row in reader:
            table_type = (row.get("table_type") or "").strip()
            status = (row.get("status_enum") or "").strip()
            assertions = _parse_assertions_count(row.get("assertions_count") or "")
            table_id = (row.get("table_id") or "").strip()
            if table_type not in G1_TABLE_TYPES or status != "PASS" or assertions != 0:
                continue
            if not table_id:
                continue
            g1_rows.append(row)

    G1_CSV.parent.mkdir(parents=True, exist_ok=True)
    with open(G1_CSV, "w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=fieldnames, extrasaction="ignore")
        w.writeheader()
        w.writerows(g1_rows)

    print(f"G1 list: {len(g1_rows)} rows -> {G1_CSV}", file=sys.stderr)
    return 0


if __name__ == "__main__":
    sys.exit(main())
