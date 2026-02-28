import sys
import pandas as pd
from quality_audit.io.word_reader import WordReader
from quality_audit.core.cache_manager import AuditContext

sys.stdout.reconfigure(encoding="utf-8")


def extract_inventories():
    doc_path = r"C:\Users\Admin\Downloads\Quality Audit Tool\data\CP Vietnam-FS2018-Consol-EN.docx"
    reader = WordReader()
    context = AuditContext()

    tables_with_context = reader.read_tables_with_headings(doc_path)
    for df, heading, table_context in tables_with_context:
        if heading and "Inventories" in heading:
            print("=== INVENTORIES TABLE ===")
            print(df.to_string())
            print(df.values.tolist())
            break


extract_inventories()
