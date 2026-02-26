# Changelog

## [2.1.0] - 2026-02-26

### New features

- **Escape Hatch**: For confidently classified primary statements (BS, P&L, CFS) that would otherwise be skipped due to low numeric evidence.
- **Roll-forward CY/PY gate bypass**: Automated movement structure detection allows validation even without explicit period headers.

### Bug fixes

- **Heading mis-detection**: `_is_heading_junk` strengthened to reject unit-only, year-only, and currency-only junk lines prevalent in Vietnamese FS.
- **Fixed Assets cross-check**: Replaced blind last-column fallback with robust `_infer_total_column` using multi-anchor row sum matching.
- **Equity double-counting**: Integrated `RowClassifier` to exclude subtotals and blank rows from movement summations.
- **Numeric normalization**: Added robustness for zero-width spaces and trailing minus signs common in Vietnamese ERP-generated formatting.

## [2.0.0] - 2026-01-23

### Breaking changes

- `WordReader.read_tables_with_headings()` now returns 3-tuple `(df, heading, table_context)` by default. Use `include_context=False` for 2-tuple backward compatibility.
- `GenericTableValidator.validate()` accepts optional `table_context` for extraction-quality gating.
- Global `cross_check_marks` is deprecated; use `AuditContext.marks` instead. Removal planned for v3.0.0.
- CLI entry point can be run via `python -m quality_audit.cli` or `main.py`.

### New features

- Feature flags system for controlling validation behaviour (see `docs/FEATURE_FLAGS.md`).
- Tax rate configuration with three modes: prompt, all, individual.
- Duplicate period column deduplication with conflict detection; conflicting columns renamed with "(2)" suffix.
- Multi-engine extraction fallback (OOXML → RenderFirst → Python-docx → legacy).
- Netting structure validation (Total - Less = Net) with configurable adjacency (`netting_adjacency_strict`, `netting_adjacency_relaxed`).
- Equity validator NO_EVIDENCE handling for zero expected values (`equity_no_evidence_not_fail`).

### Bug fixes

- Equity roll-forward formula: closing = opening + movements.
- First detail row no longer excluded from sum calculations (Issue C3).
- Statement tables: column total validation skipped where appropriate (Issue C4).
- Total column priority for BSPL cross-checks: exact "Total"/"Tổng" preferred over partial matches (Issue C1).
- Percentage value parsing and validation improvements.
- Numeric-aware empty row detection: threshold based on ≥50% amount columns or ≥2 numeric values.
- Heading junk filter relaxed; whitelist for balance sheet, income statement, cash flow, note patterns.
- Duplicate period dedup: on conflict, rename duplicate column to "(2)" instead of dropping.
