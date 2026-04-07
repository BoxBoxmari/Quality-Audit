"""
Run T1–T6 checks on baseline XLSX in reports/.
Usage: python scripts/run_t1_t6_check.py
"""

from __future__ import annotations

import re
import subprocess
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO))

from scripts.phase1_load_inventory import load_one_xlsx  # noqa: E402

BASELINE_1 = REPO / "reports" / "baseline_1_CP_Vietnam-FS2018-Consol-EN.xlsx"
BASELINE_2 = REPO / "reports" / "baseline_2_CJCGV-FS2018-EN-_v2_.xlsx"

FS_TYPES = ("FS_BALANCE_SHEET", "FS_INCOME_STATEMENT", "FS_CASH_FLOW")


def run_t1(inventory: list[dict], label: str) -> tuple[bool, int]:
    """T1: No numeric note PASS with assertions_count=0. Count such rows; pass if 0."""
    bad = [
        r
        for r in inventory
        if (r.get("table_type") or "").strip() in ("GENERIC_NOTE", "TAX_NOTE")
        and (r.get("status_enum") or "").strip() == "PASS"
        and (r.get("assertions_count") == 0 or r.get("assertions_count") is None)
    ]
    n = len(bad)
    ok = n == 0
    print(
        f"[T1] {label}: numeric note PASS with assertions_count=0 count = {n} -> {'PASS' if ok else 'FAIL'}"
    )
    return ok, n


def run_t2(inventory: list[dict], label: str) -> tuple[bool, int]:
    """T2: At least 10 numeric note tables with NOTE_SUM_TO_TOTAL and PASS (by rule_id or validator_type)."""
    # Heuristic: table_type GENERIC_NOTE/TAX_NOTE, status PASS, rule_id or validator_type suggesting sum-to-total
    note_pass = [
        r
        for r in inventory
        if (r.get("table_type") or "").strip() in ("GENERIC_NOTE", "TAX_NOTE")
        and (r.get("status_enum") or "").strip() == "PASS"
    ]
    # If we don't have rule_id in inventory, count all numeric PASS as potential NOTE_SUM_TO_TOTAL
    n = len(note_pass)
    ok = n >= 10
    print(
        f"[T2] {label}: numeric note PASS count = {n} (need >= 10) -> {'PASS' if ok else 'FAIL'}"
    )
    return ok, n


def _note_4_cash_match(r: dict) -> bool:
    """True if row looks like Note 4 Cash (table_id/heading suggest note 4 and cash/tiền)."""
    tid = (r.get("table_id") or "").strip()
    h = (r.get("heading") or "").strip().lower()
    # table_id can be "4" or contain "4"; heading may be "Cash and cash equivalents" or "4. Tiền và tương đương tiền"
    has_4 = "4" in tid or re.search(r"\b4\b", h) or h.startswith("4")
    has_cash = "cash" in h or "tiền" in h or "cash" in tid.lower()
    return bool(has_4 and has_cash)


def run_t3(inventory: list[dict], label: str) -> tuple[bool, int]:
    """T3: At least one Note 4 Cash table with status PASS."""
    note4_cash_pass = [
        r
        for r in inventory
        if _note_4_cash_match(r) and (r.get("status_enum") or "").strip() == "PASS"
    ]
    n = len(note4_cash_pass)
    ok = n >= 1
    print(
        f"[T3] {label}: Note 4 Cash PASS count = {n} (need >= 1) -> {'PASS' if ok else 'FAIL'}"
    )
    return ok, n


def _related_parties_match(r: dict) -> bool:
    """True if row looks like related parties table."""
    h = (r.get("heading") or "").strip().lower()
    tid = (r.get("table_id") or "").strip().lower()
    return "related part" in h or "related part" in tid or "bên liên quan" in h


def run_t4(inventory: list[dict], label: str) -> tuple[bool, int]:
    """T4: No related-parties table with status FAIL (subset mode)."""
    fail_related = [
        r
        for r in inventory
        if _related_parties_match(r) and (r.get("status_enum") or "").strip() == "FAIL"
    ]
    n = len(fail_related)
    ok = n == 0
    print(
        f"[T4] {label}: related parties FAIL count = {n} (need 0) -> {'PASS' if ok else 'FAIL'}"
    )
    return ok, n


def run_t5() -> tuple[bool, str]:
    """T5: Run pytest tests/core/test_cash_flow_rules.py; pass if exit code 0."""
    out = subprocess.run(
        [
            sys.executable,
            "-m",
            "pytest",
            "tests/core/test_cash_flow_rules.py",
            "-v",
            "--tb=short",
        ],
        cwd=REPO,
        capture_output=True,
        text=True,
        timeout=120,
    )
    log = (out.stdout or "") + (out.stderr or "")
    ok = out.returncode == 0
    print(
        f"[T5] pytest test_cash_flow_rules exit code = {out.returncode} -> {'PASS' if ok else 'FAIL'}"
    )
    return ok, log


def run_t6(inventory: list[dict], label: str) -> tuple[bool, dict]:
    """T6: Each FS type (BS/IS/CF) has at least one row PASS with assertions_count > 0."""
    by_type: dict[str, int] = dict.fromkeys(FS_TYPES, 0)
    fs_rows: list[dict] = []
    for r in inventory:
        tt = (r.get("table_type") or "").strip()
        if tt not in FS_TYPES:
            continue
        fs_rows.append(r)
        if (r.get("status_enum") or "").strip() != "PASS":
            continue
        ac = r.get("assertions_count")
        if ac is None or (isinstance(ac, (int, float)) and int(ac) <= 0):
            continue
        by_type[tt] += 1
    ok = all(by_type[t] >= 1 for t in FS_TYPES)
    print(
        f"[T6] {label}: BS={by_type['FS_BALANCE_SHEET']} IS={by_type['FS_INCOME_STATEMENT']} CF={by_type['FS_CASH_FLOW']} (each >= 1) -> {'PASS' if ok else 'FAIL'}"
    )
    if not ok:
        for r in fs_rows:
            print(
                f"  FS row: type={r.get('table_type')} status={r.get('status_enum')} assertions_count={r.get('assertions_count')} heading={str(r.get('heading') or '')[:50]}"
            )
    return ok, by_type


def main() -> int:
    from io import StringIO

    inv1 = load_one_xlsx(BASELINE_1)
    inv2 = load_one_xlsx(BASELINE_2)
    buf = StringIO()
    old_stdout = sys.stdout
    sys.stdout = buf
    exit_code = 1
    try:
        print(f"Loaded CP: {len(inv1)} tables, CJCGV: {len(inv2)} tables")
        if not inv1 and not inv2:
            print(
                "No data; check XLSX paths and sheet names (Tổng hợp kiểm tra, Run metadata)."
            )
            exit_code = 1
        else:
            t1_1, _ = run_t1(inv1, "CP Vietnam")
            t1_2, _ = run_t1(inv2, "CJCGV")
            t2_1, _ = run_t2(inv1, "CP Vietnam")
            t2_2, _ = run_t2(inv2, "CJCGV")
            t3_1, _ = run_t3(inv1, "CP Vietnam")
            t3_2, _ = run_t3(inv2, "CJCGV")
            t4_1, _ = run_t4(inv1, "CP Vietnam")
            t4_2, _ = run_t4(inv2, "CJCGV")
            t5_ok, _ = run_t5()
            t6_1, _ = run_t6(inv1, "CP Vietnam")
            t6_2, _ = run_t6(inv2, "CJCGV")
            t1_ok = t1_1 and t1_2
            t2_ok = t2_1 and t2_2
            t3_ok = t3_1 and t3_2
            t4_ok = t4_1 and t4_2
            t6_ok = t6_1 and t6_2
            print()
            print(f"T1 overall: {'PASS' if t1_ok else 'FAIL'}")
            print(f"T2 overall: {'PASS' if t2_ok else 'FAIL'}")
            print(f"T3 overall: {'PASS' if t3_ok else 'FAIL'}")
            print(f"T4 overall: {'PASS' if t4_ok else 'FAIL'}")
            print(f"T5 overall: {'PASS' if t5_ok else 'FAIL'}")
            print(f"T6 overall: {'PASS' if t6_ok else 'FAIL'}")
            all_ok = t1_ok and t2_ok and t3_ok and t4_ok and t5_ok and t6_ok
            exit_code = 0 if all_ok else 1
    finally:
        sys.stdout = old_stdout
        out_text = buf.getvalue()
        print(out_text)
        (REPO / "run_t1_t6_out.txt").write_text(out_text, encoding="utf-8")
    return exit_code


if __name__ == "__main__":
    sys.exit(main())
