"""
Regression test: schema tokens (Code, Note, VND, etc.) must be rejected as junk headings.
Covers P1 fix: _is_heading_junk schema-token rejection.
"""

import pytest

from quality_audit.io.word_reader import WordReader


class TestHeadingSchemaRejection:
    @pytest.fixture
    def reader(self):
        return WordReader()

    @pytest.mark.parametrize(
        "text",
        [
            "Code",
            "code",
            "Note",
            "note",
            "Notes",
            "Unit",
            "unit",
            "Mã số",
            "VND",
            "vnd",
            "USD",
            "Đơn vị",
            "STT",
            "TT",
        ],
    )
    def test_schema_tokens_rejected_as_junk(self, reader, text):
        """Standalone schema tokens must be detected as heading junk."""
        assert (
            reader._is_heading_junk(text) is True
        ), f"Expected '{text}' to be junk heading"

    @pytest.mark.parametrize(
        "text",
        [
            "Note 5: Inventories",
            "Note 10 - Revenue",
            "Statement of Cash Flows",
            "Balance Sheet",
            "Property, Plant and Equipment",
            "Investments in subsidiaries",
        ],
    )
    def test_valid_headings_not_rejected(self, reader, text):
        """Real table headings must NOT be rejected as junk."""
        assert (
            reader._is_heading_junk(text) is False
        ), f"Expected '{text}' to be a valid heading"
