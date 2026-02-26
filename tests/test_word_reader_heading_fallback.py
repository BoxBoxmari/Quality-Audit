from docx import Document

from quality_audit.io.word_reader import WordReader


class TestWordReaderHeadingFallback:
    def test_heading_from_table_first_row_when_no_paragraph_heading(self, tmp_path):
        """
        Table with no preceding paragraphs and descriptive first row
        should use first-row text as heading with heading_source='table_first_row'.
        """
        doc_path = tmp_path / "no_paragraph_heading.docx"
        doc = Document()

        table = doc.add_table(rows=3, cols=3)
        table.cell(0, 0).text = "Descriptive heading row"
        table.cell(0, 1).text = "2024"
        table.cell(0, 2).text = "2023"
        table.cell(1, 0).text = "10"
        table.cell(1, 1).text = "100"
        table.cell(1, 2).text = "90"
        table.cell(2, 0).text = "20"
        table.cell(2, 1).text = "200"
        table.cell(2, 2).text = "180"

        doc.save(str(doc_path))

        reader = WordReader()
        tables = reader.read_tables_with_headings(str(doc_path))

        assert len(tables) == 1
        df, heading, table_ctx = tables[0]

        assert heading == "Descriptive heading row"
        assert table_ctx.get("heading_source") == "table_first_row"

    def test_paragraph_heading_preferred_over_code_like_first_row(self, tmp_path):
        """
        When first rows contain only numeric/code-like cells, the reader should fall back
        to paragraph heading and not manufacture a heading from the first row.
        """
        doc_path = tmp_path / "paragraph_heading_preferred.docx"
        doc = Document()

        # Add a strong paragraph heading before the table
        para = doc.add_paragraph("Balance Sheet")
        para.style = doc.styles["Heading 1"]

        table = doc.add_table(rows=2, cols=3)
        table.cell(0, 0).text = "10"
        table.cell(0, 1).text = "100"
        table.cell(0, 2).text = "90"
        table.cell(1, 0).text = "20A"
        table.cell(1, 1).text = "200"
        table.cell(1, 2).text = "180"

        doc.save(str(doc_path))

        reader = WordReader()
        tables = reader.read_tables_with_headings(str(doc_path))

        assert len(tables) == 1
        df, heading, table_ctx = tables[0]

        # First-row cells are all numeric/code-like, so we must keep the paragraph heading
        assert heading == "Balance Sheet"
        assert table_ctx.get("heading_source") == "paragraph"
