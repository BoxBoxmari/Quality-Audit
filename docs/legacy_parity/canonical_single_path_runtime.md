# Canonical Single-Path Runtime Declaration

Production correctness is locked to a single business-logic owner:
- `legacy/main.py` (canonical source of truth)
- invoked by `AuditService.audit_document(...)`

## Active production path
- Input validation/safety shell: `FileHandler` checks
- Canonical extraction: `legacy.read_word_tables_with_headings`
- Canonical table validation: `legacy.check_table_total`
- Canonical output semantics: `legacy.write_table_sheet` + `legacy.write_summary_sheet`
- Output save shell: workbook save + return envelope

## Non-runtime semantic owners (frozen)
- `quality_audit/core/validators/*`
- `quality_audit/core/routing/table_type_classifier.py`
- `quality_audit/core/legacy_audit/engine.py`

These modules are retained for experimental/shadow/reference workflows only and must not control production correctness.

## Feature-flag policy
- Feature flags must not change production business correctness in canonical mode.
- Flags are shell/experimental controls only.

## Tax-rate shell contract
- Tax computation logic remains owned by `legacy/main.py`.
- Shell layers (CLI/GUI/batch/automation) may only supply input rate to legacy prompt boundary.
- No shell layer may alter tax business rules, fallback semantics, or decision outcomes.

## Mandatory parity check
- Run `scripts/semantic_parity_harness.py` against:
  - baseline: `C:\Users\Admin\Downloads\ABC Company-30Jun26VAS-EN.xlsx`
  - current: `C:\Users\Admin\Downloads\Quality Audit Tool\results\ABC Company-30Jun26VAS-EN.current.xlsx`
- Color parity is semantic (alpha-normalized RGB).

## Additional regression smoke artifacts (non-parity-gating)
- `C:\Users\Admin\Downloads\Quality Audit Tool\data\CP Vietnam-FS2018-Consol-EN.docx`
- `C:\Users\Admin\Downloads\Quality Audit Tool\data\CJCGV-FS2018-EN- v2 .DOCX`
