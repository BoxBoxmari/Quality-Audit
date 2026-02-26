# Definition of Done: False FAIL/INFO Reduction

Phases and acceptance for reducing false FAIL and INFO in the Quality Audit pipeline.

## Phases

| Phase | Description | Done |
|-------|-------------|------|
| 1 | Shortlist pipeline: read XLSX from `reports/`, filter FAIL/INFO, produce shortlist (JSON + MD). Placeholder when no XLSX. | Yes |
| 2 | (N/A this iteration) | - |
| 3 | Total row priority: `tighten_total_row_keywords` prefers grand_total > total > subtotal. | Yes |
| 4 | PASS gating: `treat_no_assertion_as_pass` flag; per-table log (table_id, validator, classifier, status). | Yes |
| 5 | EquityValidator: NO_EVIDENCE mapping; `equity_no_evidence_not_fail` flag. | Yes |
| 6 | Unit tests for `treat_no_assertion_as_pass`; smoke E2E for 2-DOCX regression (`run_regression_2docs`). | Yes |
| 7 | Docs: FEATURE_FLAGS.md, DoD; verify full test suite and smoke. | Yes |

## Verification commands

- **Unit (PASS gating):**  
  `pytest tests/test_base_validator.py -k TestPassGating -v`
- **Unit (equity flag):**  
  `pytest tests/test_equity_validator.py -k equity_no_evidence -v`
- **Smoke 2-DOCX:**  
  `pytest tests/integration/test_run_regression_2docs.py -v`  
  (skips if 2 default DOCX not present in tests/test_data or tests/data)
- **Full suite:**  
  `pytest tests/ -v --ignore=tests/regression`

## Exit criteria

- All phases above marked Done.
- Unit tests for PASS gating and equity flag pass.
- Smoke E2E passes when 2 DOCX exist; otherwise skips without error.
- `docs/FEATURE_FLAGS.md` and this DoD exist and are up to date.
