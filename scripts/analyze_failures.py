import os

import pandas as pd


def analyze_file(filepath):
    print(f"Analyzing {os.path.basename(filepath)}...")
    try:
        # Read 'Focus List' sheet
        df = pd.read_excel(filepath, sheet_name="Focus List")
    except Exception as e:
        print(f"Error reading 'Focus List': {e}")
        # Fallback to 'Tổng hợp kiểm tra' if Focus List doesn't exist
        try:
            df = pd.read_excel(filepath, sheet_name="Tổng hợp kiểm tra")
            # Map columns if using summary sheet
            # A: Tên bảng, B: Trạng thái kiểm tra, C: Status Enum
            df = df.rename(
                columns={
                    "Tên bảng": "Table Name",
                    "Status Enum": "Status",
                    "Trạng thái kiểm tra": "Issue Description",
                }
            )
        except Exception as e2:
            print(f"Error reading 'Tổng hợp kiểm tra': {e2}")
            return

    # Filter for FAIL/WARN
    failures = df[df["Status"].astype(str).str.contains("FAIL|WARN", na=False)]

    print(f"Total FAIL/WARN: {len(failures)}")

    # Group by Status
    print("\nCounts by Status:")
    print(failures["Status"].value_counts())

    # Detect common patterns in Table Name (Routing issues)
    print("\nTop 5 Failing Tables:")
    if "Table Name" in failures.columns:
        print(failures["Table Name"].head(5).to_string(index=False))

    # Pattern clustering (heuristic)
    routing_issues = failures[
        failures["Table Name"]
        .astype(str)
        .str.lower()
        .str.contains("note|thuyết minh", na=False)
    ]
    print(f"\nPotential Routing Issues (Note/Thuyết minh in FS): {len(routing_issues)}")
    if not routing_issues.empty:
        print(routing_issues[["Table Name", "Status"]].head(3).to_string(index=False))

    # Specific common errors
    if "Issue Description" in failures.columns:
        print("\nCommon Errors:")
        errors = failures["Issue Description"].astype(str)
        if errors.str.contains("Zero/Missing").any():
            print(f"- Zero/Missing data: {errors.str.contains('Zero/Missing').sum()}")
        if errors.str.contains("Sai lệch").any():
            print(f"- Value Mismatch: {errors.str.contains('Sai lệch').sum()}")


if __name__ == "__main__":
    import argparse

    parser = argparse.ArgumentParser(
        description="Analyze FAIL/WARN patterns in Quality Audit Excel output files"
    )
    parser.add_argument(
        "files", nargs="+", help="Paths to Excel output files to analyze"
    )
    args = parser.parse_args()

    for filepath in args.files:
        if os.path.exists(filepath):
            analyze_file(filepath)
            print("-" * 50)
        else:
            print(f"File not found: {filepath}")
