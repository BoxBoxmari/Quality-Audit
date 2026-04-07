# Parity Supported Matrix

This matrix captures current parity-lock status for high-risk behaviors.

## Status Legend

- `LOCKED`: Covered by explicit parity regression tests.
- `PARTIAL`: Behavior implemented but not fully contract-locked.
- `OUT_OF_SCOPE`: Intentionally excluded from parity lock.

## Matrix

|Area|Behavior|Status|Evidence|
|---|---|---|---|
|Routing|Parity mode blocks Big4 primary path|LOCKED|`tests/test_parity_runtime_routing.py::test_parity_mode_blocks_big4_primary_path`|
|Routing|Parity mode blocks Big4 shadow pass|LOCKED|`tests/test_parity_runtime_routing.py::test_parity_mode_blocks_big4_shadow_path`|
|Routing|FS_BALANCE_SHEET stays on `BalanceSheetValidator` when parity mode is on|LOCKED|`tests/test_table_type_classifier_balance_sheet.py::test_parity_mode_forces_balance_sheet_validator_even_without_numeric_evidence`|
|Generic validator|FORM_1 cross-check uses detected total row before fallback|LOCKED|`tests/test_generic_validator.py::test_form_1_cross_check_prefers_detected_total_row_not_last_row`|
|Tax validator|Tax reconciliation uses detected financial columns (CY/PY)|LOCKED|`tests/test_tax_validator.py::test_tax_reconciliation_uses_detected_financial_columns`|
|Balance sheet cache|AR/AP semantic aliases synced with code-based keys|LOCKED|`tests/test_balance_sheet_validator_vectorized.py::test_ar_ap_semantic_aliases_cached_for_legacy_parity`|
|Legacy combined mappings|DTA/DTL netting and combined-key parity baseline|LOCKED|`tests/test_legacy_parity_baseline.py`|
|Extraction robustness|Deterministic fallback orchestration + no-numeric-evidence dispatch contract|PARTIAL|`tests/parity/test_extraction_parity_contract.py`|

## Operational Notes

- Runtime default policy (canonical): `baseline_authoritative_default=False`,
  `legacy_bug_compatibility_mode=False`, `legacy_parity_mode=False`.
- Legacy authority is opt-in only via:
  `baseline_authoritative_default && (legacy_bug_compatibility_mode || legacy_parity_mode)`.
- If routing or cache semantics are changed, add or update parity tests in the same PR.
- Do not remove parity-lock tests without replacement coverage.

## Scope Decision (Extraction)

- Current decision: mở extraction từ `OUT_OF_SCOPE` lên `PARTIAL`.
- Locked subset: fallback orchestration deterministic + no-numeric dispatch contract.
- Remaining out-of-scope: binary/OS/OCR-dependent extraction fidelity.
