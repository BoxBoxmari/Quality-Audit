import pandas as pd
import sys
import os

sys.stdout.reconfigure(encoding="utf-8")

f = r"C:\Users\Admin\Downloads\Quality Audit Tool\results\CJCGV-FS2018-EN- v2 _output.xlsx"
if os.path.exists(f):
    xls = pd.ExcelFile(f)
    for sheet in xls.sheet_names:
        print(sheet.encode("utf-8").decode("utf-8"))
else:
    print("File not found.")
