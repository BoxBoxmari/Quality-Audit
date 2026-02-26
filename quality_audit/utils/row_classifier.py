"""
Row classification utility for financial tables.

P1-R2: Phân loại row types để exclude SECTION_TITLE từ calculations.
"""

import re
from enum import Enum
from typing import List, Optional

import pandas as pd


class RowType(Enum):
    """Row type classification for financial tables."""

    HEADER = "HEADER"
    SECTION_TITLE = "SECTION_TITLE"
    DATA = "DATA"
    SUBTOTAL = "SUBTOTAL"
    TOTAL = "TOTAL"
    FOOTER = "FOOTER"
    EMPTY = "EMPTY"


class RowClassifier:
    """Classify rows in financial tables by type."""

    # Patterns for section titles (all caps, no numbers, common financial terms)
    SECTION_TITLE_PATTERNS = [
        r"^[A-Z\s]+$",  # All uppercase letters and spaces
        r"^CASH FLOWS FROM",
        r"^CASH AND CASH EQUIVALENTS",
        r"^OPERATING ACTIVITIES",
        r"^INVESTING ACTIVITIES",
        r"^FINANCING ACTIVITIES",
        r"^ASSETS",
        r"^LIABILITIES",
        r"^EQUITY",
    ]

    # Keywords indicating totals/subtotals
    TOTAL_KEYWORDS = [
        "total",
        "tổng",
        "sum",
        "subtotal",
        "tổng cộng",
        "cộng",
        "grand total",
        "tổng số",
        "tổng hợp",
        "tổng kết",
        "cộng lại",
        "net",
        "net total",
        "tổng thuần",
        "tổng cộng cuối",
        "final total",
        "tổng cuối",
        # Additional financial statement total indicators
        "balance",
        "ending balance",
        "closing balance",
        "carrying amount",
        "carried forward",
        "brought forward",
        "số dư",
        "số dư cuối",
        "số dư đầu",
        "mang sang",
        "chuyển sang",
        "total amount",
        "aggregate",
        "sum total",
        "overall total",
    ]

    # Keywords indicating footer content
    FOOTER_KEYWORDS = [
        "note",
        "ghi chú",
        "footnote",
        "(*)",
        "(**)",
    ]

    @staticmethod
    def classify_row(row: pd.Series, header_row: Optional[pd.Series] = None) -> RowType:
        """
        Classify a single row by type.

        Args:
            row: Row data as pandas Series
            header_row: Optional header row for comparison

        Returns:
            RowType: Classified row type
        """
        # Convert row to string values for analysis
        row_str = " ".join(str(val).strip() for val in row.values if pd.notna(val))

        # Check if empty
        if not row_str or row_str.strip() == "":
            return RowType.EMPTY

        # Check if matches header (compare with header_row if provided)
        if header_row is not None:
            row_lower = row_str.lower()
            # Note: header_str calculation removed as it was unused
            # Check for common header terms with an additional year-pattern guard
            if any(
                term in row_lower
                for term in ["code", "note", "description", "account", "mã", "ghi chú"]
            ) and re.search(r"\d{4}", row_str):
                return RowType.HEADER

        # Check for section title patterns
        row_upper = row_str.upper().strip()
        for pattern in RowClassifier.SECTION_TITLE_PATTERNS:
            if re.match(pattern, row_upper, re.IGNORECASE):
                # Additional validation: should not contain significant numbers
                # (section titles are usually text-only)
                numeric_count = len(re.findall(r"\d+", row_str))
                if numeric_count <= 1:  # Allow single year or code
                    return RowType.SECTION_TITLE

        # Check for total/subtotal keywords
        row_lower = row_str.lower()
        for keyword in RowClassifier.TOTAL_KEYWORDS:
            if keyword in row_lower:
                # Check if it's a total row (usually has significant numbers)
                # Use normalize_numeric_column to handle string numbers
                from ..utils.numeric_utils import normalize_numeric_column

                numeric_values = []
                for val in row.values:
                    if pd.notna(val):
                        normalized = normalize_numeric_column(val)
                        if pd.notna(normalized) and abs(float(normalized)) > 0.01:
                            numeric_values.append(float(normalized))
                # Relaxed: require at least 1 numeric value (was >= 2)
                # This helps catch total rows with fewer numeric columns
                if len(numeric_values) >= 1:
                    # Check position: totals are usually near the end
                    return RowType.TOTAL

        # Check for footer keywords
        for keyword in RowClassifier.FOOTER_KEYWORDS:
            if keyword in row_lower:
                return RowType.FOOTER

        # Check if row has significant numeric content (data row)
        numeric_count = sum(
            1
            for val in row.values
            if pd.notna(val)
            and (
                isinstance(val, (int, float))
                or (
                    isinstance(val, str)
                    and re.match(r"^[\d,().\s-]+$", str(val).strip())
                )
            )
        )
        if numeric_count >= 2:
            return RowType.DATA

        # Default to DATA if row has any content
        return RowType.DATA

    @staticmethod
    def classify_rows(
        df: pd.DataFrame, header_row_idx: Optional[int] = None
    ) -> List[RowType]:
        """
        Classify all rows in a DataFrame.

        Args:
            df: DataFrame to classify
            header_row_idx: Optional index of header row

        Returns:
            List[RowType]: List of row types corresponding to DataFrame rows
        """
        header_row = None
        if header_row_idx is not None and 0 <= header_row_idx < len(df):
            header_row = df.iloc[header_row_idx]

        row_types = []
        for _idx, row in df.iterrows():
            row_type = RowClassifier.classify_row(row, header_row)
            row_types.append(row_type)

        return row_types

    @staticmethod
    def filter_data_rows(df: pd.DataFrame, row_types: List[RowType]) -> pd.DataFrame:
        """
        Filter DataFrame to include only DATA rows, excluding SECTION_TITLE, HEADER, etc.

        P1-R2: SECTION_TITLE rows should not be included in calculations.

        Args:
            df: DataFrame to filter
            row_types: List of RowType corresponding to df rows

        Returns:
            pd.DataFrame: Filtered DataFrame with only DATA, SUBTOTAL, and TOTAL rows
        """
        if len(row_types) != len(df):
            return df  # Return original if mismatch

        valid_types = {RowType.DATA, RowType.SUBTOTAL, RowType.TOTAL}
        mask = [rt in valid_types for rt in row_types]
        return df[mask].reset_index(drop=True)
