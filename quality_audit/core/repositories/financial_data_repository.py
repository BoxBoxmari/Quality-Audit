"""
Repository for financial data access and cross-referencing.

This repository pattern abstracts data access operations, making it easier
to swap implementations and test components in isolation.
"""

from typing import Optional, Tuple

from ..cache_manager import LRUCacheManager


class FinancialDataRepository:
    """
    Repository for financial data access and cross-referencing.

    Provides a clean interface for storing and retrieving financial statement
    data, abstracting away the underlying cache implementation.
    """

    def __init__(self, cache: LRUCacheManager):
        """
        Initialize financial data repository.

        Args:
            cache: Cache manager instance for data storage
        """
        self.cache = cache

    def save_balance_sheet_data(self, account: str, cy: float, py: float) -> None:
        """
        Save balance sheet account data for cross-referencing.

        Args:
            account: Account name or code
            cy: Current year balance
            py: Prior year balance
        """
        self.cache.set(f"bs_{account}", (cy, py))

    def get_balance_sheet_data(self, account: str) -> Optional[Tuple[float, float]]:
        """
        Retrieve balance sheet account data.

        Args:
            account: Account name or code

        Returns:
            Tuple of (current_year, prior_year) or None if not found
        """
        return self.cache.get(f"bs_{account}")

    def save_income_statement_data(self, account: str, cy: float, py: float) -> None:
        """
        Save income statement account data.

        Args:
            account: Account name or code
            cy: Current year value
            py: Prior year value
        """
        self.cache.set(f"is_{account}", (cy, py))

    def get_income_statement_data(self, account: str) -> Optional[Tuple[float, float]]:
        """
        Retrieve income statement account data.

        Args:
            account: Account name or code

        Returns:
            Tuple of (current_year, prior_year) or None if not found
        """
        return self.cache.get(f"is_{account}")

    def save_cash_flow_data(self, account: str, cy: float, py: float) -> None:
        """
        Save cash flow statement account data.

        Args:
            account: Account name or code
            cy: Current year value
            py: Prior year value
        """
        self.cache.set(f"cf_{account}", (cy, py))

    def get_cash_flow_data(self, account: str) -> Optional[Tuple[float, float]]:
        """
        Retrieve cash flow statement account data.

        Args:
            account: Account name or code

        Returns:
            Tuple of (current_year, prior_year) or None if not found
        """
        return self.cache.get(f"cf_{account}")

    def save_account_data(
        self, account: str, cy: float, py: float, statement_type: str = "generic"
    ) -> None:
        """
        Save account data with custom statement type prefix.

        Args:
            account: Account name or code
            cy: Current year value
            py: Prior year value
            statement_type: Type of financial statement (bs, is, cf, etc.)
        """
        prefix = statement_type.lower()
        self.cache.set(f"{prefix}_{account}", (cy, py))

    def get_account_data(
        self, account: str, statement_type: str = "generic"
    ) -> Optional[Tuple[float, float]]:
        """
        Retrieve account data with custom statement type prefix.

        Args:
            account: Account name or code
            statement_type: Type of financial statement (bs, is, cf, etc.)

        Returns:
            Tuple of (current_year, prior_year) or None if not found
        """
        prefix = statement_type.lower()
        return self.cache.get(f"{prefix}_{account}")

    def clear_all(self) -> None:
        """Clear all cached financial data."""
        self.cache.clear()
