import pandas as pd
import glob
import os

results_dir = r"C:\Users\Admin\Downloads\Quality Audit Tool\results"
excel_files = glob.glob(os.path.join(results_dir, "*.xlsx"))

with open(
    r"C:\Users\Admin\Downloads\Quality Audit Tool\out.txt", "w", encoding="utf-8"
) as out:
    for f in excel_files:
        out.write(f"--- File: {os.path.basename(f)} ---\n")
        try:
            df = pd.read_excel(f, sheet_name="Tổng hợp kiểm tra")
            fails = df[df["Status Enum"] == "FAIL"]
            if not fails.empty:
                for _, row in fails.iterrows():
                    out.write(f"Table ID: {row.get('Table ID', '')}\n")
                    out.write(f"Heading: {row.get('Tên bảng', '')}\n")
                    out.write(f"Status Enum: {row.get('Status Enum', '')}\n")
                    out.write(f"Trạng thái: {row.get('Trạng thái kiểm tra', '')}\n")
                    out.write("-\n")
        except Exception as e:
            out.write(f"Error reading {os.path.basename(f)}: {e}\n")
        out.write("\n")
