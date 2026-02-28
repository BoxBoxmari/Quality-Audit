import pandas as pd
import sys

sys.stdout.reconfigure(encoding="utf-8")
f = r"C:\Users\Admin\Downloads\Quality Audit Tool\results\CJCGV-FS2018-EN- v2 _output.xlsx"
xls = pd.ExcelFile(f)

found = False
for sheet in xls.sheet_names:
    if "Tổng hợp kiểm tra" in sheet or "Báo cáo" in sheet or "Summary" in sheet:
        continue
    df = pd.read_excel(f, sheet_name=sheet)
    for index, row in df.iterrows():
        # check all cols
        row_str = str(row.values)
        if "50 =" in row_str or "50=" in row_str or "Accounting profit" in row_str:
            print(f"Sheet: {sheet.encode('utf-8').decode('utf-8')}")
            print(row_str.encode("utf-8").decode("utf-8"))
            found = True
if not found:
    print("Not found anything.")
