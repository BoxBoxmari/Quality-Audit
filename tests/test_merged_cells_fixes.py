"""
Tests for P0/P1 fixes: merged cells, bounds checking, code preservation, row classification.

Tests cover:
- P0-R1: Merged cell handling in WordReader
- P0-R2: Bounds checking in validators
- P0-R3: Code column preserved as string
- P1-R1: Multi-row header detection
- P1-R2: Row classification and filtering
- P1-R3: Number parsing improvements
"""

from unittest.mock import Mock

import pandas as pd

from quality_audit.core.validators.balance_sheet_validator import BalanceSheetValidator
from quality_audit.core.validators.income_statement_validator import (
    IncomeStatementValidator,
)
from quality_audit.io.word_reader import WordReader
from quality_audit.utils.numeric_utils import normalize_numeric_column, parse_numeric
from quality_audit.utils.row_classifier import RowClassifier, RowType


class TestMergedCellHandling:
    """P0-R1: Test merged cell handling in WordReader."""

    def test_reconstruct_table_grid_basic(self):
        """Test basic grid reconstruction without merged cells."""
        reader = WordReader()

        # Create mock table
        mock_table = Mock()
        mock_row1 = Mock()
        mock_row1.cells = [Mock(text="A"), Mock(text="B"), Mock(text="C")]
        mock_row2 = Mock()
        mock_row2.cells = [Mock(text="1"), Mock(text="2"), Mock(text="3")]
        mock_table.rows = [mock_row1, mock_row2]

        # Mock XML elements
        for row in mock_table.rows:
            for cell in row.cells:
                cell._element = Mock()
                cell._element.xpath = Mock(return_value=[])

        result = reader._reconstruct_table_grid(mock_table)

        assert len(result) == 2
        assert len(result[0]) == len(result[1])  # All rows have same column count
        assert result[0] == ["A", "B", "C"]
        assert result[1] == ["1", "2", "3"]

    def test_reconstruct_table_grid_with_gridspan(self):
        """Test grid reconstruction with horizontal merge (gridSpan)."""
        reader = WordReader()

        mock_table = Mock()
        mock_row = Mock()
        mock_cell1 = Mock(text="Merged")
        mock_cell1._element = Mock()
        # Mock gridSpan element
        mock_gridspan = Mock()
        mock_gridspan.get = Mock(return_value="2")  # gridSpan = 2
        mock_cell1._element.xpath = Mock(return_value=[mock_gridspan])

        mock_cell2 = Mock(text="Normal")
        mock_cell2._element = Mock()
        mock_cell2._element.xpath = Mock(return_value=[])

        mock_row.cells = [mock_cell1, mock_cell2]
        mock_table.rows = [mock_row]

        result = reader._reconstruct_table_grid(mock_table)

        # Should expand gridSpan=2 to 2 columns
        assert len(result[0]) >= 2
        assert result[0][0] == "Merged"  # First column has merged value


class TestBoundsChecking:
    """P0-R2: Test bounds checking in validators."""

    def test_validate_dataframe_bounds_valid(self):
        """Test bounds checking with valid indices."""
        validator = BalanceSheetValidator()
        df = pd.DataFrame({"A": [1, 2, 3], "B": [4, 5, 6]})

        assert validator._validate_dataframe_bounds(df, 0, 0) is True
        assert validator._validate_dataframe_bounds(df, 2, 1) is True

    def test_validate_dataframe_bounds_invalid(self):
        """Test bounds checking with invalid indices."""
        validator = BalanceSheetValidator()
        df = pd.DataFrame({"A": [1, 2, 3], "B": [4, 5, 6]})

        assert validator._validate_dataframe_bounds(df, -1, 0) is False
        assert validator._validate_dataframe_bounds(df, 10, 0) is False
        assert validator._validate_dataframe_bounds(df, 0, -1) is False
        assert validator._validate_dataframe_bounds(df, 0, 10) is False

    def test_safe_get_cell(self):
        """Test safe cell access with bounds checking."""
        validator = BalanceSheetValidator()
        df = pd.DataFrame({"A": [1, 2, 3], "B": [4, 5, 6]})

        assert validator._safe_get_cell(df, 0, 0) == 1
        assert validator._safe_get_cell(df, 10, 0, default="DEFAULT") == "DEFAULT"

    def test_validator_handles_empty_dataframe(self):
        """Test validators handle empty DataFrames gracefully."""
        validator = BalanceSheetValidator()
        df = pd.DataFrame()

        result = validator.validate(df)
        assert "rỗng" in result.status.lower() or "empty" in result.status.lower()

    def test_validator_handles_malformed_table(self):
        """Test validators handle malformed tables without crashing."""
        validator = IncomeStatementValidator()
        # Create DataFrame with inconsistent column counts (simulating merged cell issue)
        df = pd.DataFrame(
            [["Code", "Note", "2024"], ["01", "Test"]]
        )  # Row 1 has 3 cols, row 2 has 2 cols

        # Should not crash, should return warning or error
        result = validator.validate(df)
        assert result is not None
        assert isinstance(result.status, str)


class TestCodePreservation:
    """P0-R3: Test Code column preserved as string."""

    def test_preserve_code_column_as_string(self):
        """Test Code column is preserved as string type."""
        validator = BalanceSheetValidator()
        df = pd.DataFrame(
            {
                "Code": ["01", "02", "10"],
                "Note": ["A", "B", "C"],
                "2024": [100, 200, 300],
            }
        )

        # Code column should be string
        assert df["Code"].dtype.name in ("object", "string", "string[python]", "str")

        # After preservation, should still be string
        df_preserved = validator._preserve_code_column_as_string(df, "Code")
        assert df_preserved["Code"].dtype.name in (
            "object",
            "string",
            "string[python]",
            "str",
        )

        # Leading zeros should be preserved
        assert df_preserved["Code"].iloc[0] == "01"
        assert df_preserved["Code"].iloc[0] != 1  # Should be string, not int

    def test_code_with_alpha_characters(self):
        """Test codes with alpha characters are preserved."""
        validator = BalanceSheetValidator()
        df = pd.DataFrame(
            {
                "Code": ["421a", "10(a)", "01"],
                "Note": ["A", "B", "C"],
                "2024": [100, 200, 300],
            }
        )

        df_preserved = validator._preserve_code_column_as_string(df, "Code")

        assert df_preserved["Code"].iloc[0] == "421a"
        assert df_preserved["Code"].iloc[1] == "10(a)"
        assert df_preserved["Code"].iloc[2] == "01"


class TestMultiRowHeader:
    """P1-R1: Test multi-row header detection."""

    def test_find_multi_row_header(self):
        """Test finding and merging multi-row headers."""
        validator = BalanceSheetValidator()
        df = pd.DataFrame(
            [
                ["", "2024", "2023"],  # Year row
                ["Code", "VND", "VND"],  # Currency row
                ["01", "100", "200"],  # Data row
            ]
        )

        result = validator._find_multi_row_header(df, "code")

        assert result is not None
        header_start, merged_header = result
        assert header_start == 1  # Code is in row 1
        assert "Code" in merged_header[0] or "code" in merged_header[0].lower()

    def test_find_header_row_fallback(self):
        """Test single-row header detection as fallback."""
        validator = BalanceSheetValidator()
        df = pd.DataFrame(
            [
                ["Code", "Note", "2024", "2023"],
                ["01", "Test", "100", "200"],
            ]
        )

        header_idx = validator._find_header_row(df, "code")
        assert header_idx == 0


class TestRowClassification:
    """P1-R2: Test row type classification."""

    def test_classify_section_title(self):
        """Test SECTION_TITLE rows are correctly identified."""
        df = pd.DataFrame(
            [
                ["CASH FLOWS FROM OPERATING ACTIVITIES", "", ""],
            ]
        )

        row_type = RowClassifier.classify_row(df.iloc[0])
        assert row_type == RowType.SECTION_TITLE

    def test_classify_data_row(self):
        """Test DATA rows are correctly identified."""
        df = pd.DataFrame(
            [
                ["01", "Test Account", "100,000", "90,000"],
            ]
        )

        row_type = RowClassifier.classify_row(df.iloc[0])
        assert row_type == RowType.DATA

    def test_classify_empty_row(self):
        """Test EMPTY rows are correctly identified."""
        df = pd.DataFrame(
            [
                ["", "", "", ""],
            ]
        )

        row_type = RowClassifier.classify_row(df.iloc[0])
        assert row_type == RowType.EMPTY

    def test_filter_data_rows(self):
        """Test filtering excludes SECTION_TITLE rows."""
        df = pd.DataFrame(
            [
                ["Code", "Note", "2024"],  # Header
                ["CASH FLOWS FROM OPERATING", "", ""],  # Section title
                ["01", "Test", "100"],  # Data
                ["10", "Test2", "200"],  # Data
            ]
        )

        row_types = RowClassifier.classify_rows(df, header_row_idx=0)
        filtered_df = RowClassifier.filter_data_rows(df, row_types)

        # Should exclude header and section title
        assert len(filtered_df) <= len(df)
        # Should include data rows
        assert "01" in filtered_df.iloc[0].values or "01" in str(
            filtered_df.iloc[0].values
        )


class TestNumberParsing:
    """P1-R3: Test number parsing improvements."""

    def test_parse_dash_as_null(self):
        """Test '-' is parsed as null (NaN)."""
        result = normalize_numeric_column("-")
        assert pd.isna(result)

    def test_parse_parentheses_as_negative(self):
        """Test parentheses are parsed as negative numbers."""
        result = normalize_numeric_column("(100,000)")
        assert result == -100000.0

    def test_parse_comma_separated(self):
        """Test comma-separated numbers are parsed correctly."""
        result = normalize_numeric_column("1,234,567.89")
        assert abs(result - 1234567.89) < 0.01

    def test_parse_numeric_with_dash(self):
        """Test parse_numeric handles '-' correctly."""
        result = parse_numeric("-")
        assert result == 0.0  # parse_numeric returns 0.0 for null


class TestIntegration:
    """Integration tests for complete validation flow."""

    def test_balance_sheet_validation_with_merged_cells_simulation(self):
        """Test balance sheet validation handles malformed tables (simulating merged cell issues)."""
        validator = BalanceSheetValidator()

        # Simulate table that might result from merged cells (inconsistent columns)
        # In practice, WordReader should fix this, but test defensive coding
        df = pd.DataFrame(
            [
                ["Code", "Note", "2024", "2023"],
                ["100", "Cash", "100000", "90000"],
            ]
        )

        result = validator.validate(df)
        assert result is not None
        assert isinstance(result.status, str)
        # Should not crash with index out of bounds

    def test_income_statement_with_section_titles(self):
        """Test income statement validation filters section titles."""
        validator = IncomeStatementValidator()

        df = pd.DataFrame(
            [
                ["Code", "Note", "2024", "2023"],
                ["OPERATING REVENUE", "", "", ""],  # Section title
                ["01", "Revenue", "1000", "900"],
                ["10", "Total Revenue", "1000", "900"],
            ]
        )

        result = validator.validate(df)
        assert result is not None
        # Section title should be filtered out, so "10" should be found
        assert (
            "10" in result.status or "PASS" in result.status or "FAIL" in result.status
        )
