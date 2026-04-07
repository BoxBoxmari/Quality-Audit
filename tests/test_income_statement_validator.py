"""
Tests for IncomeStatementValidator cross-check cache logic.
"""

import pandas as pd

from quality_audit.core.cache_manager import cross_check_cache, cross_check_marks
from quality_audit.core.validators.income_statement_validator import (
    IncomeStatementValidator,
)


class TestIncomeStatementCrossCheckCache:
    """Test income statement validator cross-check cache functionality."""

    def setup_method(self):
        """Clear cache and marks before each test."""
        cross_check_cache.clear()
        cross_check_marks.clear()

    def test_store_account_name_from_note_column(self):
        """Test that account names from note column are stored in cache."""
        df = pd.DataFrame(
            {
                "Account": ["Revenue", "Cost", "Profit"],
                "Code": ["01", "02", "10"],
                "Note": ["", "N1", ""],
                "2024": [1000, 500, 500],
                "2023": [900, 450, 450],
            }
        )

        validator = IncomeStatementValidator()
        validator.validate(df)

        # Verify: Account name from note column should be in cache
        assert "cost" in cross_check_cache
        cached_value = cross_check_cache.get("cost")
        assert cached_value == (500.0, 450.0)

    def test_aggregate_51_52_to_income_tax(self):
        """Test that codes '51' and '52' aggregate into 'income tax'."""
        df = pd.DataFrame(
            {
                "Account": ["Tax 1", "Tax 2"],
                "Code": ["51", "52"],
                "Note": ["N1", "N2"],
                "2024": [100, 50],
                "2023": [90, 45],
            }
        )

        validator = IncomeStatementValidator()
        validator.validate(df)

        # Verify: 'income tax' should contain sum of '51' and '52'
        cached_value = cross_check_cache.get("income tax")
        assert cached_value == (150.0, 135.0)  # 100+50, 90+45

    def test_store_code_50_in_cache(self):
        """Test that code '50' is stored in cache."""
        df = pd.DataFrame(
            {
                "Account": ["Profit"],
                "Code": ["50"],
                "Note": [""],  # No note
                "2024": [500],
                "2023": [450],
            }
        )

        validator = IncomeStatementValidator()
        validator.validate(df)

        # Verify: Code '50' should be in cache
        cached_value = cross_check_cache.get("50")
        assert cached_value == (500.0, 450.0)

    def test_code_30_cp_variant_with_plus_24(self):
        """CP-like variant: 30 = 20 + 21 - 22 + 24 - 25 - 26."""
        df = pd.DataFrame(
            {
                "Account": [
                    "Code 20",
                    "Code 21",
                    "Code 22",
                    "Code 24",
                    "Code 25",
                    "Code 26",
                    "Code 30",
                ],
                "Code": ["20", "21", "22", "24", "25", "26", "30"],
                "Note": ["", "", "", "", "", "", ""],
                "2024": [100.0, 20.0, 10.0, 5.0, 15.0, 10.0, 90.0],
                "2023": [90.0, 10.0, 5.0, 4.0, 9.0, 6.0, 84.0],
            }
        )

        validator = IncomeStatementValidator()
        result = validator.validate(df)

        assert result.status.startswith("PASS:")
        assert result.context.get("formula_variant_code_30") == "cp_variant_plus_24"

    def test_code_30_cj_variant_without_24_23_27(self):
        """CJ-like variant: 30 = 20 + 21 - 22 - 25 - 26."""
        df = pd.DataFrame(
            {
                "Account": [
                    "Code 20",
                    "Code 21",
                    "Code 22",
                    "Code 25",
                    "Code 26",
                    "Code 30",
                ],
                "Code": ["20", "21", "22", "25", "26", "30"],
                "Note": ["", "", "", "", "", ""],
                "2024": [100.0, 20.0, 10.0, 15.0, 10.0, 85.0],
                "2023": [90.0, 10.0, 5.0, 9.0, 6.0, 80.0],
            }
        )
        validator = IncomeStatementValidator()
        result = validator.validate(df)
        assert result.status.startswith("PASS:")
        assert result.context.get("formula_variant_code_30") == "cj_variant_no_24_23_27"

    def test_code_30_prefers_explicit_row_formula(self):
        """Explicit inline formula on row text must override inferred variant."""
        df = pd.DataFrame(
            {
                "Account": [
                    "20",
                    "21",
                    "22",
                    "24",
                    "25",
                    "26",
                    "Lợi nhuận (30 = 20 + 21 - 22 - 25 - 26)",
                ],
                "Code": ["20", "21", "22", "24", "25", "26", "30"],
                "2024": [100.0, 20.0, 10.0, 999.0, 15.0, 10.0, 85.0],
                "2023": [90.0, 10.0, 5.0, 888.0, 9.0, 6.0, 80.0],
            }
        )
        validator = IncomeStatementValidator()
        result = validator.validate(df)
        assert result.status.startswith("PASS:")
        assert result.context.get("formula_variant_code_30") == "explicit_formula_text"
