"""
KPI Baseline Script — reads 2 output.xlsx files and produces coverage metrics.

Usage:
    python scripts/kpi_baseline.py [--json-out kpi.json]

Outputs:
    - Markdown report (stdout)
    - Optional JSON (for CI comparison)
"""

import json
import sys
from pathlib import Path

import pandas as pd

RESULTS_DIR = Path(__file__).resolve().parent.parent / "results"
FILES = [
    "CJCGV-FS2018-EN- v2 _output.xlsx",
    "CP Vietnam-FS2018-Consol-EN_output.xlsx",
]

# Status categories
UNEXPECTED_NO_EVIDENCE_INDICATORS = [
    "không có evidence (unexpected)",
    "RULES_RAN_BUT_NO_EVIDENCE",
    "REGISTRY_MISS",
    "NO_RULES_FOR_TYPE",
    "PARSE_FAIL_NUMERIC",
    "MODEL_BUCKET_MISS",
    "SCOPE_FAIL",
    "chưa áp dụng quy tắc NOTE_SUM_TO_TOTAL",
    "chưa phân loại hoặc không có assertions",
    "không có assertions cụ thể",
]

NOTE_TYPES = {"GENERIC_NOTE", "TAX_NOTE"}


def _is_unexpected_no_evidence(row: pd.Series) -> bool:
    """Check if a row represents a NOTE numeric table with no useful evidence."""
    status = str(row.get("Status", "")).strip()
    table_type = str(row.get("Loại bảng", row.get("Table Type", ""))).strip().upper()
    status_enum = str(row.get("Status Enum", row.get("StatusEnum", ""))).strip().upper()

    # Must be NOTE-type
    if table_type not in NOTE_TYPES and "NOTE" not in table_type:
        return False

    # Check against indicators
    for indicator in UNEXPECTED_NO_EVIDENCE_INDICATORS:
        if indicator.lower() in status.lower():
            return True

    # INFO_SKIPPED on numeric NOTE
    return (
        status_enum in ("INFO_SKIPPED", "INFO")
        and "NOTE" in table_type
        and ("số" in status.lower() or "numeric" in status.lower())
    )


def _analyze_file(xlsx_path: Path) -> dict:
    """Analyze one output xlsx and return KPI metrics."""
    xls = pd.ExcelFile(xlsx_path)

    # Try to find the summary sheet
    summary_sheet = None
    for s in xls.sheet_names:
        if "tổng hợp" in s.lower() or "summary" in s.lower() or "kiểm tra" in s.lower():
            summary_sheet = s
            break

    if not summary_sheet:
        summary_sheet = xls.sheet_names[0] if xls.sheet_names else None

    results = {
        "file": xlsx_path.name,
        "total_tables": 0,
        "note_tables": 0,
        "note_numeric_tables": 0,
        "note_unexpected_no_evidence": 0,
        "note_pass": 0,
        "note_fail": 0,
        "note_warn": 0,
        "note_info_skipped": 0,
        "focus_list_total": 0,
        "focus_list_fail": 0,
        "status_distribution": {},
        "unexpected_tables": [],
    }

    if summary_sheet:
        df = pd.read_excel(xlsx_path, sheet_name=summary_sheet)
        results["total_tables"] = len(df)

        for _, row in df.iterrows():
            table_type = (
                str(row.get("Loại bảng", row.get("Table Type", ""))).strip().upper()
            )
            status_enum = (
                str(row.get("Status Enum", row.get("StatusEnum", ""))).strip().upper()
            )
            status = str(row.get("Status", "")).strip()

            # Count status distribution
            results["status_distribution"][status_enum] = (
                results["status_distribution"].get(status_enum, 0) + 1
            )

            # NOTE tables
            if "NOTE" in table_type or table_type in NOTE_TYPES:
                results["note_tables"] += 1

                # Check if numeric
                is_numeric = (
                    "số" in status.lower()
                    or "numeric" in status.lower()
                    or "PASS" in status_enum
                    or "FAIL" in status_enum
                    or "WARN" in status_enum
                )
                if is_numeric:
                    results["note_numeric_tables"] += 1

                if status_enum == "PASS":
                    results["note_pass"] += 1
                elif status_enum in ("FAIL", "ERROR"):
                    results["note_fail"] += 1
                elif status_enum == "WARN":
                    results["note_warn"] += 1
                elif status_enum in ("INFO_SKIPPED", "INFO"):
                    results["note_info_skipped"] += 1

                if _is_unexpected_no_evidence(row):
                    results["note_unexpected_no_evidence"] += 1
                    table_id = row.get("Table ID", row.get("Mã bảng", "?"))
                    heading = row.get("Heading", row.get("Tiêu đề", "?"))
                    results["unexpected_tables"].append(
                        {
                            "table_id": str(table_id),
                            "heading": str(heading)[:60],
                            "status": status[:80],
                        }
                    )

    # Focus List
    focus_sheet = None
    for s in xls.sheet_names:
        if "focus" in s.lower():
            focus_sheet = s
            break

    if focus_sheet:
        df_focus = pd.read_excel(xlsx_path, sheet_name=focus_sheet)
        results["focus_list_total"] = len(df_focus)
        for _, row in df_focus.iterrows():
            sev = str(row.get("Severity", row.get("Mức độ", ""))).strip().upper()
            if "FAIL" in sev or "MAJOR" in sev or "CRITICAL" in sev:
                results["focus_list_fail"] += 1

    return results


def main():
    json_out = None
    if "--json-out" in sys.argv:
        idx = sys.argv.index("--json-out")
        json_out = sys.argv[idx + 1] if idx + 1 < len(sys.argv) else "kpi_baseline.json"

    all_results = []
    for fname in FILES:
        fpath = RESULTS_DIR / fname
        if not fpath.exists():
            print(f"WARNING: {fpath} not found, skipping.")
            continue
        all_results.append(_analyze_file(fpath))

    # Print markdown report
    print("# KPI Baseline Report\n")
    for r in all_results:
        print(f"## {r['file']}\n")
        print("| Metric | Value |")
        print("|--------|-------|")
        print(f"| Total tables | {r['total_tables']} |")
        print(f"| NOTE tables | {r['note_tables']} |")
        print(f"| NOTE numeric | {r['note_numeric_tables']} |")
        print(
            f"| NOTE unexpected no evidence (K1) | **{r['note_unexpected_no_evidence']}** |"
        )
        print(f"| NOTE PASS | {r['note_pass']} |")
        print(f"| NOTE FAIL | {r['note_fail']} |")
        print(f"| NOTE WARN | {r['note_warn']} |")
        print(f"| NOTE INFO_SKIPPED | {r['note_info_skipped']} |")
        print(f"| Focus List total | {r['focus_list_total']} |")
        print(f"| Focus List FAIL (K2) | **{r['focus_list_fail']}** |")
        print(f"\nStatus distribution: {r['status_distribution']}\n")
        if r["unexpected_tables"]:
            print(
                f"### Unexpected no-evidence tables ({len(r['unexpected_tables'])})\n"
            )
            print("| Table ID | Heading | Status |")
            print("|----------|---------|--------|")
            for t in r["unexpected_tables"][:20]:
                print(f"| {t['table_id']} | {t['heading']} | {t['status'][:60]} |")
            print()

    # JSON output
    if json_out:
        with open(json_out, "w", encoding="utf-8") as f:
            json.dump(all_results, f, indent=2, ensure_ascii=False, default=str)
        print(f"\nJSON written to {json_out}")


if __name__ == "__main__":
    main()
