# P1-1 Gold Set Fixtures

## Purpose

This directory contains the gold set fixtures for regression testing of the render-first table extraction pipeline. These fixtures represent tables that previously failed with `FAIL_TOOL_EXTRACT` status due to conversion issues.

## Directory Structure

```
gold_set/
├── README.md           # This file
├── manifest.json       # Legacy pointer to gold_set_manifest.json
└── ground_truth/       # Ground truth CSVs for each table
    └── CJCGV_table_006.csv
```

## Manifest

The gold set manifest is located at `../gold_set_manifest.json` and contains:

- **fail_tool_extract_tables**: List of 20 tables from FAIL_TOOL_EXTRACT status
  - 9 tables from CJCGV-FS2018-EN
  - 10 tables from CP Vietnam-FS2018-Consol-EN
  - 1 table from test_single_table
- **edge_cases**: Placeholders for rule_b_blank_label, equity_validator, tax_validator cases

## Usage

### Running Regression Tests

```bash
pytest tests/regression/test_render_first_regression.py -v
```

### Adding Ground Truth

To add ground truth for a table:

1. Extract the expected CSV from the original DOCX
2. Save as `ground_truth/{source_file_prefix}_table_{index:03d}.csv`
3. Update the manifest if needed

## Table Reference

| Source File                 | Table Indices                       |
| --------------------------- | ----------------------------------- |
| CJCGV-FS2018-EN             | 6, 12, 13, 21, 26, 28, 29, 33, 46   |
| CP Vietnam-FS2018-Consol-EN | 4, 7, 9, 12, 14, 26, 31, 37, 48, 50 |
| test_single_table           | 1                                   |

## Expected Outcomes

Per `test_render_first_regression.py`:

- Target: Reduce FAIL_TOOL_EXTRACT from 20 to ≤10 (50% reduction)
- No silent PASS with low confidence (< 0.7)
- Mean CER < 0.05 on gold set
