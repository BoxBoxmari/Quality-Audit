"""
Unit tests for ColumnDetector utility.
"""

import pandas as pd

from quality_audit.utils.column_detector import ColumnDetector


class TestColumnDetector:
    """Test cases for ColumnDetector."""

    def test_detect_financial_columns_year_patterns(self):
        """Test detection with year patterns."""
        df = pd.DataFrame(
            {
                "Code": ["100", "200"],
                "Account": ["Asset", "Liability"],
                "2024": [1000, 2000],
                "2023": [900, 1800],
            }
        )

        cur_col, prior_col = ColumnDetector.detect_financial_columns_advanced(df)
        assert cur_col == "2024"
        assert prior_col == "2023"

    def test_detect_financial_columns_cy_py_patterns(self):
        """Test detection with CY/PY patterns."""
        df = pd.DataFrame(
            {
                "Code": ["100", "200"],
                "Account": ["Asset", "Liability"],
                "CY2024": [1000, 2000],
                "PY2023": [900, 1800],
            }
        )

        cur_col, prior_col = ColumnDetector.detect_financial_columns_advanced(df)
        assert cur_col == "CY2024"
        assert prior_col == "PY2023"

    def test_detect_financial_columns_financial_terms(self):
        """Test detection with financial terms."""
        df = pd.DataFrame(
            {
                "Code": ["100", "200"],
                "Account": ["Asset", "Liability"],
                "Current Year": [1000, 2000],
                "Prior Year": [900, 1800],
            }
        )

        cur_col, prior_col = ColumnDetector.detect_financial_columns_advanced(df)
        assert cur_col == "Current Year"
        assert prior_col == "Prior Year"

    def test_detect_financial_columns_vietnamese_terms(self):
        """Test detection with Vietnamese terms."""
        df = pd.DataFrame(
            {
                "Code": ["100", "200"],
                "Account": ["Asset", "Liability"],
                "Năm hiện tại": [1000, 2000],
                "Năm trước": [900, 1800],
            }
        )

        cur_col, prior_col = ColumnDetector.detect_financial_columns_advanced(df)
        assert cur_col == "Năm hiện tại"
        assert prior_col == "Năm trước"

    def test_detect_financial_columns_fallback(self):
        """Test fallback to last two columns when patterns don't match."""
        df = pd.DataFrame(
            {
                "Code": ["100", "200"],
                "Account": ["Asset", "Liability"],
                "Column A": [1000, 2000],
                "Column B": [900, 1800],
            }
        )

        cur_col, prior_col = ColumnDetector.detect_financial_columns_advanced(df)
        assert cur_col == "Column A"
        assert prior_col == "Column B"

    def test_detect_financial_columns_empty_dataframe(self):
        """Test detection with empty DataFrame."""
        df = pd.DataFrame()
        cur_col, prior_col = ColumnDetector.detect_financial_columns_advanced(df)
        assert cur_col is None
        assert prior_col is None

    def test_detect_financial_columns_single_column(self):
        """Test detection with single column."""
        df = pd.DataFrame({"Code": ["100"], "2024": [1000]})

        cur_col, prior_col = ColumnDetector.detect_financial_columns_advanced(df)
        # Should fallback to last column and None
        assert cur_col == "2024"
        assert prior_col is None

    def test_detect_code_column(self):
        """Test code column detection."""
        df = pd.DataFrame({"Code": ["100", "200"], "Account": ["Asset", "Liability"]})

        code_col = ColumnDetector.detect_code_column(df)
        assert code_col == "Code"

    def test_detect_code_column_partial_match(self):
        """Test code column detection with partial match."""
        df = pd.DataFrame(
            {"Account Code": ["100", "200"], "Account": ["Asset", "Liability"]}
        )

        code_col = ColumnDetector.detect_code_column(df)
        assert code_col == "Account Code"

    def test_detect_note_column(self):
        """Test note column detection."""
        df = pd.DataFrame({"Code": ["100", "200"], "Note": ["Note 1", "Note 2"]})

        note_col = ColumnDetector.detect_note_column(df)
        assert note_col == "Note"

    def test_has_year_pattern(self):
        """Test year pattern detection."""
        assert ColumnDetector.has_year_pattern("2024")
        assert ColumnDetector.has_year_pattern("CY2024")
        assert ColumnDetector.has_year_pattern("Year 2024")
        assert not ColumnDetector.has_year_pattern("Account")

    def test_extract_year_from_column(self):
        """Test year extraction from column name."""
        assert ColumnDetector.extract_year_from_column("2024") == 2024
        assert ColumnDetector.extract_year_from_column("CY2024") == 2024
        assert ColumnDetector.extract_year_from_column("Year 2024") == 2024
        assert ColumnDetector.extract_year_from_column("Account") is None
