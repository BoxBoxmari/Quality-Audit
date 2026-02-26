#!/usr/bin/env python3
"""
Quality Audit - Output Analysis Script
Analyzes Excel output files to extract metadata and status counts.
"""
import argparse
import json
import os
import sys

import pandas as pd


def analyze_output_file(filepath: str) -> dict:
    """Analyze a single output Excel file."""
    if not os.path.exists(filepath):
        return {"error": f"File not found: {filepath}"}

    try:
        xls = pd.ExcelFile(filepath)
    except Exception as e:
        return {"error": f"Failed to read Excel file: {e}"}

    result = {
        "file": os.path.basename(filepath),
        "sheets": xls.sheet_names,
        "has_run_metadata": "Run metadata" in xls.sheet_names,
    }

    # Find summary sheet and count statuses
    for sheet in xls.sheet_names:
        try:
            df = pd.read_excel(filepath, sheet_name=sheet)
            for col in df.columns:
                col_str = str(col).lower()
                if "status" in col_str or "trang" in col_str:
                    vals = df[col].astype(str)
                    result["status_counts"] = {
                        "ERROR": int(vals.str.contains("ERROR", case=False).sum()),
                        "WARN": int(vals.str.contains("WARN", case=False).sum()),
                        "PASS": int(vals.str.contains("PASS", case=False).sum()),
                        "FAIL": int(vals.str.contains("FAIL", case=False).sum()),
                        "INFO": int(vals.str.contains("INFO", case=False).sum()),
                    }
                    break
            if "status_counts" in result:
                break
        except Exception:
            continue

    # Check Run metadata content
    if result["has_run_metadata"]:
        try:
            meta = pd.read_excel(filepath, sheet_name="Run metadata")
            result["metadata_preview"] = meta.head(10).to_dict()
        except Exception:
            pass

    return result


def main():
    """Main function."""
    parser = argparse.ArgumentParser(
        description="Analyze Quality Audit Excel output files"
    )
    parser.add_argument(
        "files", nargs="+", help="Paths to Excel output files to analyze"
    )
    parser.add_argument(
        "--json", action="store_true", help="Output as JSON instead of formatted text"
    )
    args = parser.parse_args()

    results = {}
    for filepath in args.files:
        name = os.path.splitext(os.path.basename(filepath))[0]
        results[name] = analyze_output_file(filepath)

    if args.json:
        print(json.dumps(results, indent=2, default=str))
    else:
        for name, result in results.items():
            print(f"\n{name}:")
            print(f"  Sheets: {result.get('sheets', [])}")
            print(f"  Has Run Metadata: {result.get('has_run_metadata', False)}")
            if "status_counts" in result:
                print(f"  Status Counts: {result['status_counts']}")

    return 0


if __name__ == "__main__":
    sys.exit(main())
