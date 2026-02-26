"""
Tests for FinancialDataRepository.
"""

import pytest

from quality_audit.core.cache_manager import LRUCacheManager
from quality_audit.core.repositories.financial_data_repository import (
    FinancialDataRepository,
)


class TestFinancialDataRepository:
    """Tests for financial data repository pattern."""

    @pytest.fixture
    def repository(self):
        """Create repository instance for testing."""
        cache = LRUCacheManager(max_size=100)
        return FinancialDataRepository(cache=cache)

    def test_save_and_get_balance_sheet_data(self, repository):
        """Test saving and retrieving balance sheet data."""
        account = "cash_and_cash_equivalents"
        cy_value = 1000.0
        py_value = 900.0

        repository.save_balance_sheet_data(account, cy_value, py_value)
        result = repository.get_balance_sheet_data(account)

        assert result is not None
        assert result == (cy_value, py_value)

    def test_save_and_get_income_statement_data(self, repository):
        """Test saving and retrieving income statement data."""
        account = "revenue"
        cy_value = 5000.0
        py_value = 4500.0

        repository.save_income_statement_data(account, cy_value, py_value)
        result = repository.get_income_statement_data(account)

        assert result is not None
        assert result == (cy_value, py_value)

    def test_save_and_get_cash_flow_data(self, repository):
        """Test saving and retrieving cash flow data."""
        account = "operating_activities"
        cy_value = 2000.0
        py_value = 1800.0

        repository.save_cash_flow_data(account, cy_value, py_value)
        result = repository.get_cash_flow_data(account)

        assert result is not None
        assert result == (cy_value, py_value)

    def test_get_nonexistent_account(self, repository):
        """Test retrieving non-existent account returns None."""
        result = repository.get_balance_sheet_data("nonexistent_account")
        assert result is None

    def test_save_account_data_with_custom_type(self, repository):
        """Test saving account data with custom statement type."""
        account = "custom_account"
        cy_value = 3000.0
        py_value = 2800.0

        repository.save_account_data(account, cy_value, py_value, "custom")
        result = repository.get_account_data(account, "custom")

        assert result is not None
        assert result == (cy_value, py_value)

    def test_clear_all_data(self, repository):
        """Test clearing all cached data."""
        repository.save_balance_sheet_data("account1", 100.0, 90.0)
        repository.save_income_statement_data("account2", 200.0, 190.0)

        repository.clear_all()

        assert repository.get_balance_sheet_data("account1") is None
        assert repository.get_income_statement_data("account2") is None

    def test_data_isolation_between_statement_types(self, repository):
        """Test that data is isolated between different statement types."""
        account = "same_account_name"

        repository.save_balance_sheet_data(account, 100.0, 90.0)
        repository.save_income_statement_data(account, 200.0, 190.0)

        bs_data = repository.get_balance_sheet_data(account)
        is_data = repository.get_income_statement_data(account)

        assert bs_data == (100.0, 90.0)
        assert is_data == (200.0, 190.0)
        assert bs_data != is_data
