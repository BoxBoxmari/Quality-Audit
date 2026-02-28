"""
Document-level financial model holding all classified tables.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from typing import Any

logger = logging.getLogger(__name__)


@dataclass
class FinancialModel:
    """Document-level aggregator of classified tables."""

    income_statements: list[dict[str, Any]] = field(default_factory=list)
    balance_sheets: list[dict[str, Any]] = field(default_factory=list)
    cash_flows: list[dict[str, Any]] = field(default_factory=list)
    equity_changes: list[dict[str, Any]] = field(default_factory=list)
    notes: list[dict[str, Any]] = field(default_factory=list)

    def add_table(self, table_info: dict[str, Any]) -> None:
        """
        Add a classified table to the model.

        Args:
            table_info: Dict containing at least 'df' and 'table_type'.
        """
        table_type = table_info.get("table_type", "")
        if "FS_INCOME_STATEMENT" in table_type:
            self.income_statements.append(table_info)
        elif "FS_BALANCE_SHEET" in table_type:
            self.balance_sheets.append(table_info)
        elif "FS_CASH_FLOW" in table_type:
            self.cash_flows.append(table_info)
        elif "FS_EQUITY" in table_type:
            self.equity_changes.append(table_info)
        elif "NOTE" in table_type:
            self.notes.append(table_info)
        else:
            logger.debug("Unknown table type %s added to model.", table_type)

    def get_line_item(
        self, statement_type: str, code: str, col_idx: int = 0
    ) -> float | None:
        """
        Lookup a specific line item by code.

        Args:
            statement_type: E.g., "FS_BALANCE_SHEET"
            code: The line item code (e.g., "270")
            col_idx: Index into amount_cols (0 for current year, 1 for previous)

        Returns:
            The float value if found and numeric, else None.
        """
        tables = []
        if "FS_INCOME_STATEMENT" in statement_type:
            tables = self.income_statements
        elif "FS_BALANCE_SHEET" in statement_type:
            tables = self.balance_sheets
        elif "FS_CASH_FLOW" in statement_type:
            tables = self.cash_flows
        elif "FS_EQUITY" in statement_type:
            tables = self.equity_changes
        elif "NOTE" in statement_type:
            tables = self.notes
        else:
            logger.warning("Unknown statement_type: %s", statement_type)
            return None

        code_str = str(code).strip()
        if code_str.isdigit() and len(code_str) == 1:
            code_str = f"0{code_str}"

        for t in tables:
            df = t.get("df")
            code_col = t.get("code_col")
            amount_cols = t.get("amount_cols", [])

            if df is None or not code_col or not amount_cols:
                continue

            if col_idx >= len(amount_cols):
                continue

            amount_col = amount_cols[col_idx]
            if code_col not in df.columns or amount_col not in df.columns:
                continue

            for _, row in df.iterrows():
                row_code = str(row[code_col]).strip()
                if row_code.isdigit() and len(row_code) == 1:
                    row_code = f"0{row_code}"
                if row_code == code_str:
                    try:
                        return float(row[amount_col])
                    except (ValueError, TypeError):
                        pass
        return None
