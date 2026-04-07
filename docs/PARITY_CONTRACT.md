# Legacy Parity Contract

This document defines runtime parity guarantees between the modern audit pipeline and legacy behavior in `legacy/main.py` and `legacy/Quality Audit.py`.

## Scope

Parity guarantees apply to:

- Table routing and validator selection in parity mode.
- Cross-table cache semantics used by reconciliation checks.
- Total-row and amount-column selection used by critical validations.
- Deterministic extraction robustness contracts:
  - fallback orchestration order and trigger behavior,
  - no-numeric-evidence handling contract at validator dispatch boundary.

Out of scope:

- Extraction fidelity differences that depend on binary toolchains/OS/OCR stack
  and cannot be made deterministic in unit/integration tests.
- Non-blocking observability metadata.

## Runtime Contract

### 1) Parity mode routing dominance

When `legacy_parity_mode=True`:

- `AuditService` must not execute Big4 as primary path.
- `AuditService` must not run the Big4 shadow comparison pass (`enable_big4_shadow` is ignored; parity output must match legacy-only semantics without a secondary Big4 run).
- `ValidatorFactory` must return `BalanceSheetValidator` for `FS_BALANCE_SHEET` regardless of numeric-evidence gating.

Locked by tests:

- `tests/test_parity_runtime_routing.py::test_parity_mode_blocks_big4_primary_path`
- `tests/test_parity_runtime_routing.py::test_parity_mode_blocks_big4_shadow_path`
- `tests/test_table_type_classifier_balance_sheet.py::test_parity_mode_forces_balance_sheet_validator_even_without_numeric_evidence`

### 2) FORM_1 total-row parity

`GenericTableValidator._handle_cross_check_form_1` must use detected total row (`_find_total_row`) when available, with fallback to the last row only when detection is unavailable.

Locked by test:

- `tests/test_generic_validator.py::test_form_1_cross_check_prefers_detected_total_row_not_last_row`

### 3) Tax reconciliation column parity

`TaxValidator._validate_tax_reconciliation` must use detected financial columns from `ColumnDetector.detect_financial_columns_advanced()` (current/prior year), not hardcoded last-2 columns.

Locked by test:

- `tests/test_tax_validator.py::test_tax_reconciliation_uses_detected_financial_columns`

### 4) AR/AP semantic alias parity

Balance-sheet processing must populate cache with both code-based keys (`131/211/331/311`) and semantic aliases expected by legacy parity mappings.

Locked by test:

- `tests/test_balance_sheet_validator_vectorized.py::test_ar_ap_semantic_aliases_cached_for_legacy_parity`

## Change Policy

- Any modification that can alter the above semantics must include:
  - A dedicated parity test update.
  - A short parity rationale in PR description.
- Parity tests are non-optional for refactors touching routing, cache keys, total-row selection, or tax column detection.

## Extraction Contract (Partial)

The following extraction-related behaviors are contract-locked (deterministic subset):

- Low-quality OOXML path attempts `render_first` before Python-docx when the
  render-first trigger condition is met.
- High-quality OOXML path does not invoke `render_first` in signals-only mode.
- `AuditService._validate_single_table` returns `NO_NUMERIC_EVIDENCE` (INFO)
  when validator dispatch yields `SKIPPED_NO_NUMERIC_EVIDENCE` under parity mode.

Evidence tests:

- `tests/parity/test_extraction_parity_contract.py::test_render_first_triggered_before_python_docx_on_low_quality`
- `tests/parity/test_extraction_parity_contract.py::test_render_first_not_triggered_when_ooxml_quality_is_good`
- `tests/parity/test_extraction_parity_contract.py::test_parity_no_numeric_dispatch_returns_info_no_numeric_evidence`
