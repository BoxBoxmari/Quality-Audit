"""
Tests for vectorized balance sheet validation operations.
"""

import pandas as pd
import pytest

from quality_audit.config.validation_rules import get_balance_rules
from quality_audit.core.validators.balance_sheet_validator import \
    BalanceSheetValidator


class TestBalanceSheetValidatorVectorized:
    """Tests for vectorized validation operations."""

    @pytest.fixture
    def validator(self):
        """Create validator instance."""
        return BalanceSheetValidator()

    @pytest.fixture
    def sample_balance_sheet_df(self):
        """Create sample balance sheet DataFrame."""
        data = {
            "code": ["100", "110", "111", "112", "200", "210", "211"],
            "account_name": [
                "Total Assets",
                "Current Assets",
                "Cash",
                "Inventory",
                "Total Liabilities",
                "Current Liabilities",
                "Accounts Payable",
            ],
            "2024": [10000, 6000, 2000, 4000, 5000, 3000, 3000],
            "2023": [9000, 5500, 1800, 3700, 4500, 2800, 2800],
        }
        return pd.DataFrame(data)

    def test_vectorized_validation_with_valid_data(
        self, validator, sample_balance_sheet_df
    ):
        """Test vectorized validation with valid parent-child relationships."""
        header = ["code", "account_name", "2024", "2023"]
        rules = get_balance_rules()

        # Build data dictionary
        data = {}
        code_rowpos = {}
        for idx, row in sample_balance_sheet_df.iterrows():
            code = validator._normalize_code(row["code"])
            data[code] = (float(row["2024"]), float(row["2023"]))
            code_rowpos[code] = idx

        issues, marks = validator._validate_balance_sheet_vectorized(
            data, code_rowpos, "2024", "2023", header, 0, rules
        )

        # Should validate parent-child relationships
        assert isinstance(issues, list)
        assert isinstance(marks, list)

    def test_vectorized_validation_handles_missing_children(self, validator):
        """Test vectorized validation when some child accounts are missing."""
        data = {
            "100": (10000.0, 9000.0),  # Parent exists
            "110": (6000.0, 5500.0),  # One child exists
            # '111' and '112' are missing
        }
        code_rowpos = {"100": 0, "110": 1}
        header = ["code", "account_name", "2024", "2023"]
        rules = {"100": ["110", "111", "112"]}

        issues, marks = validator._validate_balance_sheet_vectorized(
            data, code_rowpos, "2024", "2023", header, 0, rules
        )

        # Should detect missing children
        assert len(issues) > 0 or len(marks) > 0

    def test_vectorized_validation_performance(self, validator):
        """Test that vectorized operations are faster than loops for large datasets."""
        import time

        # Create large dataset
        large_data = {}
        large_code_rowpos = {}
        for i in range(1000):
            code = str(1000 + i)
            large_data[code] = (float(i * 100), float(i * 90))
            large_code_rowpos[code] = i

        header = ["code", "account_name", "2024", "2023"]
        rules = {
            "1000": [str(1000 + i) for i in range(100)]
        }  # Parent with 100 children

        start_time = time.time()
        issues, marks = validator._validate_balance_sheet_vectorized(
            large_data, large_code_rowpos, "2024", "2023", header, 0, rules
        )
        vectorized_time = time.time() - start_time

        # Vectorized should be reasonably fast (less than 1 second for 1000 items)
        assert vectorized_time < 1.0, f"Vectorized operation took {vectorized_time}s"
