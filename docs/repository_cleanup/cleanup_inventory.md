# Repository Cleanup Inventory

## Scope
One-shot cleanup and structural normalization focused on dead/generated clutter and root-level loose artifacts, while preserving baseline/runtime/test/parity integrity.

## Baseline-Protected (KEEP_BASELINE)
- `legacy/main.py`
- `legacy/Quality Audit.py`
- `docs/legacy_parity/*`
- `tests/parity/*`
- `tests/golden_expectations/*`

## High-Confidence Cleanup Targets
- Tracked Python bytecode and `__pycache__` under `quality_audit/`, `tests/`, `scripts/`.
- Root-level generated/stray artifacts:
  - `quality_audit.zip`
  - `quality_audit_legacy_parity_report.docx`
  - `TASK.md` (root duplicate context doc)
  - `todos.md`
  - `gap_report.csv` (moved under `reports/`)
  - `log.txt`
- Tool caches:
  - `.mypy_cache/`
  - `.pytest_cache/`

## Root-Level File Classification (meaningful non-standard)
- `main.py` -> KEEP_ACTIVE (CLI wrapper, referenced by docs/config/tests)
- `openmemory.md` -> KEEP_DOC_OR_EVIDENCE (referenced in docs)
- `quality_audit.zip` -> MOVE_TO_ARCHIVE
- `quality_audit_legacy_parity_report.docx` -> MOVE_TO_BETTER_LOCATION
- `TASK.md` -> MOVE_TO_ARCHIVE (active task doc is `docs/TASK.md`)
- `todos.md` -> MOVE_TO_ARCHIVE
- `gap_report.csv` -> MOVE_TO_BETTER_LOCATION (`reports/`)
- `log.txt` -> MOVE_TO_ARCHIVE

## Structural Actions
- Added cleanup docs under `docs/repository_cleanup/`.
- Added archive folders:
  - `archive/deprecated_docs/`
  - `archive/misc_reference/`
- Added parity evidence folder:
  - `docs/legacy_parity/evidence/`

## Safety Notes
- No legacy baseline source was deleted.
- No runtime package module relocation was applied in this pass.
- No test fixture/golden/parity manifest removal was applied.
