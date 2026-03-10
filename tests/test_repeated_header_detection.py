"""Tests for repeated-header detection in WordReader (G2)."""

import pandas as pd
import pytest

from quality_audit.io.word_reader import WordReader


@pytest.fixture
def reader():
    return WordReader()


class TestFindRepeatedHeaderRow:
    """Tests for WordReader._find_repeated_header_row."""

    def test_repeated_header_splits_table(self, reader):
        """A body row with year tokens matching column headers is detected."""
        df = pd.DataFrame(
            {
                "Code": ["01", "02", "2023", "03", "04"],
                "2023": [100, 200, "2023", 300, 400],
                "2022": [90, 180, "2022", 270, 360],
            }
        )
        idx = reader._find_repeated_header_row(df)
        assert idx == 2  # row with "2023"/"2022" in body

    def test_no_repeated_header(self, reader):
        """Normal table without repeated headers returns None."""
        df = pd.DataFrame(
            {
                "Code": ["01", "02", "03", "04", "05"],
                "2023": [100, 200, 300, 400, 500],
                "2022": [90, 180, 270, 360, 450],
            }
        )
        idx = reader._find_repeated_header_row(df)
        assert idx is None

    def test_too_short_table(self, reader):
        """Tables with fewer than 3 rows return None."""
        df = pd.DataFrame(
            {
                "Code": ["01", "02"],
                "2023": [100, 200],
                "2022": [90, 180],
            }
        )
        idx = reader._find_repeated_header_row(df)
        assert idx is None

    def test_no_year_in_headers(self, reader):
        """If column headers have no year tokens, returns None."""
        df = pd.DataFrame(
            {
                "Description": ["A", "B", "C", "D"],
                "Amount": [100, 200, 300, 400],
                "Note": ["n1", "n2", "n3", "n4"],
            }
        )
        idx = reader._find_repeated_header_row(df)
        assert idx is None
