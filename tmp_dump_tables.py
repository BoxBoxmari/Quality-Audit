import pandas as pd
from quality_audit.io.word_reader import WordReader
from quality_audit.core.cache_manager import AuditContext, LRUCacheManager


def list_headings(doc_path):
    reader = WordReader()
    context = AuditContext()

    tables_with_context = reader.read_tables_with_headings(doc_path)
    print(f"File: {doc_path}")
    for table_info in tables_with_context:
        df, heading, table_context = table_info
        print(f" - {heading}")


print("----- CJCGV -----")
list_headings(
    r"C:\Users\Admin\Downloads\Quality Audit Tool\data\CJCGV-FS2018-EN- v2 .docx"
)

print("\n\n----- CP Vietnam -----")
list_headings(
    r"C:\Users\Admin\Downloads\Quality Audit Tool\data\CP Vietnam-FS2018-Consol-EN.docx"
)
