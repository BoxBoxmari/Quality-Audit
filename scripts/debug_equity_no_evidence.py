"""Temporary debug script for equity NO_EVIDENCE test. Run from repo root."""

import sys
from pathlib import Path

_project_root = Path(__file__).resolve().parent.parent
if str(_project_root) not in sys.path:
    sys.path.insert(0, str(_project_root))

import pandas as pd  # noqa: E402

from quality_audit.core.validators.equity_validator import EquityValidator  # noqa: E402

import quality_audit.core.validators.equity_validator as ev_mod  # noqa: E402

df = pd.DataFrame(
    [
        ["Label", "Amount", "Total owners' equity"],
        ["Balance at beginning", "", ""],
        ["Balance at end", 50, 100],
    ]
)

orig = ev_mod.get_feature_flags


def flags_on():
    f = dict(orig())
    f["equity_no_evidence_not_fail"] = True
    f["equity_header_infer"] = False
    return f


ev_mod.get_feature_flags = flags_on

validator = EquityValidator()
result = validator.validate(df, table_context={})

out_path = _project_root / "reports" / "debug_equity_out.txt"
out_path.parent.mkdir(parents=True, exist_ok=True)
with open(out_path, "w", encoding="utf-8") as out:
    out.write(f"status: {result.status}\n")
    out.write(f"len(marks): {len(result.marks)}\n")
    for i, m in enumerate(result.marks):
        out.write(f"  mark {i}: {m}\n")
    no_ev = [
        m
        for m in result.marks
        if m.get("comment") and "NO_EVIDENCE" in (m.get("comment") or "")
    ]
    out.write(f"no_evidence_marks: {len(no_ev)}\n")
    for m in no_ev:
        out.write(f"  {m}\n")
