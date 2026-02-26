"""
Dump table column names from DOCX files for code-column detection tuning.

Usage:
  python -m scripts.dump_table_columns "path/to/file.docx"
  python -m scripts.dump_table_columns "path/to/folder"

Output: one line per table: file | idx | heading | repr(columns)
"""

import sys
from pathlib import Path


def find_docx(path: Path) -> list[Path]:
    if path.is_file() and path.suffix.lower() == ".docx":
        return [path]
    if path.is_dir():
        return sorted(path.glob("**/*.docx"))
    return []


def main() -> int:
    if len(sys.argv) < 2:
        print("Usage: python -m scripts.dump_table_columns <file.docx|folder>")
        return 1
    # Add project root so quality_audit is importable when running as a script
    project_root = Path(__file__).resolve().parent.parent
    if str(project_root) not in sys.path:
        sys.path.insert(0, str(project_root))

    from quality_audit.io.word_reader import WordReader

    input_path = Path(sys.argv[1])
    if not input_path.exists():
        print(f"Path does not exist: {input_path}")
        return 1
    docx_files = find_docx(input_path)
    if not docx_files:
        print(f"No .docx files found under: {input_path}")
        return 1
    reader = WordReader()
    for file_path in docx_files:
        try:
            triples = reader.read_tables_with_headings(str(file_path))
        except Exception as e:
            print(f"{file_path.name}\tERROR\t{e}")
            continue
        for idx, (df, heading, _ctx) in enumerate(triples):
            cols = list(df.columns) if df is not None and not df.empty else []
            heading_short = (heading or "")[:60].replace("\t", " ").replace("\n", " ")
            print(f"{file_path.name}\t{idx}\t{heading_short}\t{cols!r}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
