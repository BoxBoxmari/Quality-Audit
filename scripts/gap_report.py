"""
Pha 4: Gap report script.
Reads 2 output xlsx + optional log, writes CSV/Excel with:
  file_name, table_id, heading, proposed_validation, reason
"""

from __future__ import annotations

import argparse
import csv
import sys
from pathlib import Path

# Allow running from project root or from scripts/
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from scripts.phase1_load_inventory import DEFAULT_XLSX, load_inventory  # noqa: E402


def build_report_rows(inventory: list[dict]) -> list[dict]:
    """Map inventory to gap report rows (file_name, table_id, heading, proposed_validation, reason)."""
    rows = []
    for row in inventory:
        proposed = (row.get("rule_id") or "").strip() or (
            row.get("validator_type") or ""
        ).strip()
        reason = (row.get("failure_reason_code") or "").strip()
        rows.append(
            {
                "file_name": (row.get("file_name") or "").strip(),
                "table_id": (row.get("table_id") or "").strip(),
                "heading": (row.get("heading") or "").strip(),
                "proposed_validation": proposed,
                "reason": reason,
            }
        )
    return rows


def write_csv(rows: list[dict], out_path: Path) -> None:
    """Write rows to CSV with header file_name, table_id, heading, proposed_validation, reason."""
    fieldnames = ["file_name", "table_id", "heading", "proposed_validation", "reason"]
    with out_path.open("w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=fieldnames)
        w.writeheader()
        w.writerows(rows)


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Gap report: xlsx + optional log -> CSV/Excel"
    )
    parser.add_argument(
        "--xlsx",
        nargs="*",
        default=None,
        help="Paths to *_output.xlsx (default: 2 files in results/)",
    )
    parser.add_argument(
        "--log",
        type=Path,
        default=None,
        help="Optional audit log path (reason can be augmented from log later)",
    )
    parser.add_argument(
        "--out",
        type=Path,
        default=Path("reports/gap_report.csv"),
        help="Output CSV path (default: reports/gap_report.csv)",
    )
    args = parser.parse_args()

    xlsx_paths = [Path(p) for p in (args.xlsx or DEFAULT_XLSX)]
    for p in xlsx_paths:
        if not p.exists():
            print(f"Missing xlsx: {p}", file=sys.stderr)
            return 1

    inventory = load_inventory(xlsx_paths)
    if not inventory:
        print("No tables loaded.", file=sys.stderr)
        return 1

    rows = build_report_rows(inventory)
    args.out.parent.mkdir(parents=True, exist_ok=True)
    write_csv(rows, args.out)
    print(f"Wrote {len(rows)} rows to {args.out}")
    if args.log and args.log.exists():
        # Reserved: future augmentation of reason from log
        pass
    return 0


if __name__ == "__main__":
    sys.exit(main())
