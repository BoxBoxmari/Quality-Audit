"""
Tests for heading_inference_v2: junk filter, proximity, section boundary,
heading_source and heading_confidence in table_ctx.
"""

from quality_audit.io.word_reader import WordReader


class TestHeadingInferenceV2:
    """Tests for heading inference v2 in WordReader."""

    def test_read_tables_with_headings_returns_table_ctx_with_heading_source(
        self, sample_word_file
    ):
        """Each (df, heading_str, table_ctx) has table_ctx['heading_source']."""
        reader = WordReader()
        result = reader.read_tables_with_headings(sample_word_file)
        assert isinstance(result, list)
        assert len(result) >= 1
        for _df, _heading_str, table_ctx in result:
            assert table_ctx is not None
            assert "heading_source" in table_ctx
            assert table_ctx["heading_source"] in ("paragraph", "table_first_row")

    def test_read_tables_with_headings_returns_heading_confidence(
        self, sample_word_file
    ):
        """table_ctx includes heading_confidence when v2/heading logic runs."""
        reader = WordReader()
        result = reader.read_tables_with_headings(sample_word_file)
        assert len(result) >= 1
        for _df, _heading_str, table_ctx in result:
            assert "heading_confidence" in table_ctx
            conf = table_ctx["heading_confidence"]
            assert conf is None or (0.0 <= conf <= 1.0)
