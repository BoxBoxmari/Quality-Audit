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
