# Final Gap Report

## Date
- 2026-03-23

## One-Pass Closure Summary
- Legacy semantic union was completed in baseline core catalogs/codes/headings.
- Default runtime decision ownership was moved to `legacy_audit.router` + `legacy_audit.engine` via `AuditService` baseline path.
- Modern decision-shaping heuristics were kept available but off-default unless explicitly enabled via nonbaseline/experimental/shadow flags.
- CTK is now the real default UI path with no silent automatic Tk fallback.
- Excel layer remained renderer/stability focused; no semantic redesign introduced.

## Runtime Authority Statement
- Default audit path is **modern/classifier-first** and does **not** import legacy scripts by file path.
- Legacy-authoritative path is opt-in only when:
  `baseline_authoritative_default && (legacy_bug_compatibility_mode || legacy_parity_mode)`.
- Root-level `main.py` is not authoritative baseline.

## Documentation Canonical Source
- Canonical runtime policy lives in `docs/parity/baseline-policy.md`.
- This report is historical execution evidence and must not override canonical policy statements.

## Verification (this pass)
- `python -m compileall quality_audit` -> success.
- `python -m pytest -q` -> `675 passed, 17 skipped, 0 failed`.
- `python scripts/run_regression_2docs.py` -> success; wrote `reports/baseline_2docs.md`.
- `python scripts/aggregate_failures.py reports/baseline_1_CP_Vietnam-FS2018-Consol-EN.xlsx reports/baseline_2_CJCGV-FS2018-EN-_v2_.xlsx` -> `total_fail_warn_rows=0`, `group_count=0`.
- `python scripts/gap_report.py` -> wrote `gap_report.csv` (133 rows).
- `python scripts/freeze_parity_baseline.py` -> wrote `parity/baselines/baseline_meta.json`, copied `parity/baselines/aggregate_failures.json`.
- `python -m quality_audit.cli --help` -> success.
- GUI smoke (`python -m quality_audit.ui_ctk`) -> process alive after 5s (manual terminate).

## Gap Closure in This Pass
- Closed regression-safety gap where baseline mode did not force-disable nonbaseline code-pattern routing fallback.
  - Updated `quality_audit/config/feature_flags.py` (`_FORCED_FALSE_WHEN_BASELINE_DEFAULT`) to force:
    - `nonbaseline_code_pattern_routing_fallback=False`.
  - Updated tests:
    - `tests/test_feature_flags_parity_force.py`
    - `tests/parity/test_legacy_router_isolation.py`

## Residual Gap
- No blocking functional gap remains against current acceptance gates.
- Non-blocking technical debt remains:
  - legacy global cache compatibility still exists in codebase (warning is now
    controlled via targeted pytest `filterwarnings`, but debt remains until
    full context-injection migration is complete).
