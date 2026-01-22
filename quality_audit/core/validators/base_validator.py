"""
Base validator class for financial statement validation.
"""

from abc import ABC, abstractmethod
from typing import Any, Dict, List

import pandas as pd

from ...config.constants import TABLES_NEED_CHECK_SEPARATELY, VALID_CODES
from ...utils.numeric_utils import normalize_numeric_column
from ..cache_manager import cross_check_cache


class ValidationResult:
    """Standardized validation result structure."""

    def __init__(
        self, status: str, marks: List[Dict] = None, cross_ref_marks: List[Dict] = None
    ):
        """
        Initialize validation result.

        Args:
            status: Human-readable status message
            marks: List of cell marks for formatting
            cross_ref_marks: List of cross-reference marks
        """
        self.status = status
        self.marks = marks or []
        self.cross_ref_marks = cross_ref_marks or []

    def to_dict(self) -> Dict[str, Any]:
        """Convert to dictionary format."""
        return {
            "status": self.status,
            "marks": self.marks,
            "cross_ref_marks": self.cross_ref_marks,
        }


class BaseValidator(ABC):
    """
    Abstract base class for financial statement validators.

    Defines the interface that all validators must implement.
    """

    def __init__(self, cache_manager=None):
        """
        Initialize validator.

        Args:
            cache_manager: Cache manager for cross-referencing data
        """
        self.cache_manager = cache_manager

    @abstractmethod
    def validate(self, df: pd.DataFrame, heading: str = None) -> ValidationResult:
        """
        Validate a financial statement table.

        Args:
            df: DataFrame containing the table data
            heading: Table heading for context

        Returns:
            ValidationResult: Validation results with status and marks
        """
        pass

    def _find_header_row(self, df: pd.DataFrame, code_col_name: str = "code") -> int:
        """
        Find the header row containing the code column.

        Args:
            df: DataFrame to search
            code_col_name: Name of the code column

        Returns:
            int: Index of header row, or None if not found
        """
        for i in range(len(df)):
            row_strs = df.iloc[i].astype(str).str.lower()
            if row_strs.str.contains(code_col_name.lower()).any():
                return i
        return None

    def _normalize_code(self, code: str) -> str:
        """
        Normalize account code for consistent processing.

        Args:
            code: Raw code string

        Returns:
            str: Normalized uppercase code
        """
        import re

        s = str(code).strip()
        s = (
            s.replace("_", "")
            .replace("**", "")
            .replace("\u2212", "-")
            .replace("–", "-")
        )
        s = re.sub(r"[^0-9A-Za-z]", "", s)
        return s.upper()

    def _convert_to_numeric_df(self, df: pd.DataFrame) -> pd.DataFrame:
        """
        Convert entire DataFrame to numeric values.

        Args:
            df: Input DataFrame

        Returns:
            pd.DataFrame: DataFrame with numeric conversion applied
        """
        return df.map(normalize_numeric_column)

    def _validate_code_format(self, code: str) -> bool:
        """
        Validate account code format (digits optionally followed by letter).

        Args:
            code: Code to validate

        Returns:
            bool: True if code format is valid
        """
        import re

        return bool(re.match(r"^[0-9]+[A-Z]?$", code))

    def _find_total_row(self, df: pd.DataFrame) -> int:
        """
        Find the total row using heuristics.

        Args:
            df: DataFrame to search

        Returns:
            int: Index of total row, or None if not found
        """

        # Implementation from original code
        def _as_numeric_series(row):
            return row.map(normalize_numeric_column)

        def _is_numeric_row(row) -> bool:
            ser = _as_numeric_series(row)
            return ser.notna().any()

        def _is_empty_row(row) -> bool:
            def _strip_text(x):
                s = str(x).strip()
                s = s.replace("-", "").replace("–", "").replace("—", "")
                s = s.replace("(", "").replace(")", "").replace(",", "")
                return s.strip()

            has_text = any(_strip_text(c) != "" for c in row)
            has_num = _is_numeric_row(row)
            return (not has_text) and (not has_num)

        numeric_rows = [i for i in range(len(df)) if _is_numeric_row(df.iloc[i])]
        if not numeric_rows:
            return None

        # Find row with empty row before it
        for i in reversed(numeric_rows):
            prev_empty = True
            if i - 1 >= 0:
                prev_empty = _is_empty_row(df.iloc[i - 1])
            if prev_empty:
                return i

        return numeric_rows[-1]  # Fallback to last numeric row

    def cross_check_with_BSPL(
        self,
        df: pd.DataFrame,
        cross_ref_marks: List[Dict],
        issues: List[str],
        account_name: str,
        CY_bal: float,
        PY_bal: float,
        CY_row: int,
        CY_col: int,
        gap_row: int,
        gap_col: int,
    ) -> None:
        """
        Cross-check current table values with cached BSPL values.

        Args:
            df: DataFrame containing the table
            cross_ref_marks: List to append cross-reference marks to
            issues: List to append issues to
            account_name: Account name to cross-check
            CY_bal: Current year balance from current table
            PY_bal: Prior year balance from current table
            CY_row: Current year row index
            CY_col: Current year column index
            gap_row: Row gap for prior year position
            gap_col: Column gap for prior year position
        """
        cached_value = cross_check_cache.get(account_name)
        if cached_value is None:
            return  # No cached value to compare against

        BSPL_CY_bal, BSPL_PY_bal = cached_value

        # Calculate differences
        diffCB = BSPL_CY_bal - CY_bal
        diffOB = BSPL_PY_bal - PY_bal
        is_okCB = abs(round(diffCB)) == 0
        is_okOB = abs(round(diffOB)) == 0

        # Adjust position for special cases
        adjusted_CY_row = CY_row
        adjusted_CY_col = CY_col

        if (
            account_name in TABLES_NEED_CHECK_SEPARATELY
            or account_name in VALID_CODES
            or account_name
            in ["50", "construction in progress", "long-term prepaid expenses"]
            or "revenue" in account_name
        ):
            adjusted_CY_row = CY_row - 1
            adjusted_CY_col = len(df.columns)

        # Create cross-reference marks for current year
        commentCB = (
            f"BSPL = {BSPL_CY_bal:,.2f}, Note = {CY_bal:,.2f}, Sai lệch = {diffCB:,.0f}"
        )
        cross_ref_marks.append(
            {
                "row": adjusted_CY_row,
                "col": adjusted_CY_col,
                "ok": is_okCB,
                "comment": None if is_okCB else commentCB,
            }
        )
        if not is_okCB:
            issues.append(commentCB)

        # Create cross-reference marks for prior year
        commentOB = (
            f"BSPL = {BSPL_PY_bal:,.2f}, Note = {PY_bal:,.2f}, Sai lệch = {diffOB:,.0f}"
        )
        cross_ref_marks.append(
            {
                "row": adjusted_CY_row - gap_row,
                "col": adjusted_CY_col - gap_col,
                "ok": is_okOB,
                "comment": None if is_okOB else commentOB,
            }
        )
        if not is_okOB:
            issues.append(commentOB)
