# Quality Audit – Scripts

Utility scripts for diagnostics, analysis, and installation verification.

## Usage

### verify_installation.py

Verifies Python version and dependencies (pandas, numpy, openpyxl, python-docx, tkinter).

```bash
python scripts/verify_installation.py
# or
python -m scripts.verify_installation
```

No arguments. Exit 0 if all checks pass.

### analyze_failures.py

Analyzes Excel audit output for FAIL/WARN rows (sheet "Focus List" or "Tổng hợp kiểm tra").

```bash
python scripts/analyze_failures.py path/to/audit_output.xlsx
```

### analyze_output.py

Summarizes audit Excel output (sheets, row counts, status distribution).

```bash
python scripts/analyze_output.py path/to/audit_output.xlsx
```

### dump_table_columns.py

Dumps table column names from DOCX files for code-column detection tuning.

```bash
python -m scripts.dump_table_columns path/to/file.docx
python -m scripts.dump_table_columns path/to/folder
```

Output: one line per table: `file | idx | heading | repr(columns)`.

### forensic_parse.py

Forensic parsing of DOCX/Excel for debugging extractor behavior. Check script for required args and paths.

```bash
python scripts/forensic_parse.py [args]
```

### evaluate_render_first.py

Evaluates render-first extractor on given inputs. Check script for args and env (e.g. Poppler).

```bash
python scripts/evaluate_render_first.py [args]
```

### run_regression_2docs.py

Runs audit pipeline on two DOCX paths and writes a report (e.g. reports/after_2docs.md).

```bash
python scripts/run_regression_2docs.py <doc1> <doc2> --report-name after_2docs.md --prefix after
```

### parse_audit_xlsx.py

Parses audit XLSX output for analysis. Check script for input path and output options.

```bash
python scripts/parse_audit_xlsx.py [path/to/audit.xlsx]
```

### analyze_xlsx.py

Analyzes XLSX structure/contents. Check script for args.

```bash
python scripts/analyze_xlsx.py [path/to/file.xlsx]
```

### aggregate_failures.py

Aggregates failure stats from audit XLSX; used with run_regression_2docs output.

```bash
python scripts/aggregate_failures.py [path/to/audit.xlsx]
```

### extract_gold_set.py

Extracts FAIL_TOOL_EXTRACT table IDs from audit XLSX output and writes gold-set manifest. Run from repo root.

```bash
python scripts/extract_gold_set.py [--results-dir DIR] [--manifest PATH]
```

Default: `--results-dir=./results`, `--manifest=tests/fixtures/gold_set_manifest.json`.

### verify_p0_columns.py

Verifies P0 columns (Render First Rejection, Mean Cell Confidence, etc.) in audit XLSX output. Run from repo root.

```bash
python scripts/verify_p0_columns.py path/to/audit_output.xlsx
```

### debug_equity_no_evidence.py

Temporary debug script for equity NO_EVIDENCE behavior. Writes to `reports/debug_equity_out.txt`. Run from repo root.

```bash
python scripts/debug_equity_no_evidence.py
```

## Dependencies

Same as main package: pandas, openpyxl, python-docx. Run from repo root so `quality_audit` is importable for `dump_table_columns.py`.
