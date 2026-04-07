# Excel Stability Scope

- Baseline styling semantics are centralized in `quality_audit/core/legacy_audit/coloring.py`.
- `quality_audit/io/excel_writer.py` remains output renderer/orchestrator, not decision owner.
- Output-stage contract:
  - no PASS/WARN/FAIL reinterpretation at write time,
  - preserve mark comments and cross-reference hints from validation context,
  - keep workbook/hyperlink sanitation and safe save lifecycle.
- Regression evidence:
  - `scripts/run_regression_2docs.py` and aggregate checks pass with `total_fail_warn_rows=0`.
