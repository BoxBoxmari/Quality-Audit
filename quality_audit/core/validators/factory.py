"""
Validator factory for creating appropriate validators based on table type.
"""

from typing import Optional

import pandas as pd

from .balance_sheet_validator import BalanceSheetValidator
# Import here to avoid circular imports
from .base_validator import BaseValidator
from .cash_flow_validator import CashFlowValidator
from .equity_validator import EquityValidator
from .generic_validator import GenericTableValidator
from .income_statement_validator import IncomeStatementValidator
from .tax_validator import TaxValidator


class ValidatorFactory:
    """Factory for creating table validators based on content analysis."""

    @staticmethod
    def get_validator(table: pd.DataFrame, heading: Optional[str]) -> BaseValidator:
        """
        Determine appropriate validator based on table content and heading.

        This replicates the routing logic from the original check_table_total() function
        (lines 1179-1191 in legacy Quality Audit.py).

        Args:
            table: DataFrame containing table data
            heading: Table heading text

        Returns:
            BaseValidator: Appropriate validator instance
        """
        heading_lower = heading.lower().strip() if heading else ""

        # Financial statement type detection - matching original routing logic
        if heading_lower == "balance sheet":
            return BalanceSheetValidator()
        elif heading_lower == "statement of income":
            return IncomeStatementValidator()
        elif heading_lower == "statement of cash flows":
            return CashFlowValidator()
        elif heading_lower == "changes in owners' equity":
            return EquityValidator()
        elif "reconciliation of effective tax rate" in heading_lower:
            return TaxValidator()
        elif (
            "recognised in the statement of income" in heading_lower
            or "recognised in the balance sheet" in heading_lower
            or "recognised in consolidated statement of income" in heading_lower
            or "deferred tax assets and liabilities" in heading_lower
            or "deferred tax assets" in heading_lower
            or "deferred tax liabilities" in heading_lower
            or "recognised in consolidated balance sheet" in heading_lower
        ):
            return TaxValidator()
        else:
            # Generic validator for other tables - matches original fallback
            return GenericTableValidator()
