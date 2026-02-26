# P0 Extraction Loss (Missing Amount Columns) – Investigation and Fix

This document describes the steps to trace, fix, and regress the P0 extraction issue where some tables (e.g. CJCGV tbl_006 Cash flow, and two other affected tables) lose amount columns in the pipeline.

## 1. Trace extraction pipeline

- Enable DEBUG logging: `logging.getLogger("quality_audit").setLevel(logging.DEBUG)`.
- Run audit on one of the affected documents (e.g. CJCGV tbl_006 Cash flow) and capture logs.
- Trace flow:
  - `word_reader.read_tables_with_headings()` → `_extract_table_with_fallback()` → extractor engine → DataFrame output.
- Log `shape` and `columns` at each step (e.g. after OOXML extractor, after header promotion, after dedup, after role inference).

## 2. Identify root cause

Check in order:

- **OOXML extractor** (`ooxml_table_grid_extractor.py`): `grid_cols_expected` vs `grid_cols_built` match?
- **Header promotion** (`word_reader._promote_header_row()`): Are amount columns dropped because rows are misidentified as header?
- **Duplicate period dedup** (`table_normalizer._dedup_period_columns()`): Are amount columns dropped by duplicate period key?
- **Column role inference** (`column_roles.infer_column_roles()`): Are amount columns classified as `ROLE_NUMERIC`?

## 3. Implement fix

Depending on root cause:

- **OOXML grid corruption:** Improve `ooxml_table_grid_extractor.py` merged-cell handling.
- **Header promotion:** Fix `word_reader._promote_header_row()` to preserve amount columns.
- **Dedup:** Fix `table_normalizer._dedup_period_columns()` so columns with data are not dropped (conflict path already renames to "(2)").
- **Role inference:** Fix `column_roles.infer_column_roles()` so amount columns are detected correctly.

## 4. Add regression test

For the three affected tables, add assertions:

```python
amount_cols = [c for c in df.columns if "amount" in str(c).lower() or is_numeric_column(c)]
assert len(amount_cols) >= 2
assert df[amount_cols].notna().sum().sum() > 0
```

See `tests/test_remediation_fixes.py` → `TestP0ExtractionAmountColumns` for a test stub that runs when CJCGV document is available.

## 5. Verify fix

- Run full audit on CJCGV and CP Vietnam.
- Check output XLSX for amount data in the previously affected tables.
