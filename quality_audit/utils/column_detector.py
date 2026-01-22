"""
Advanced column detection utilities for financial tables.

Provides enhanced pattern matching for detecting financial columns,
including year patterns, currency symbols, and multi-language support.
"""

import re
from typing import Optional, Tuple

import pandas as pd


class ColumnDetector:
    """Advanced column detection for financial tables with enhanced patterns."""

    # Year detection patterns
    YEAR_PATTERNS = [
        r"\d{4}",  # 2024, 2023
        r"\d{1,2}/\d{1,2}/\d{2,4}",  # 31/12/2024, 12/31/24
        r"CY\s*\d{4}",  # CY2024, CY 2024
        r"PY\s*\d{4}",  # PY2023, PY 2023
        r"Year\s+\d{4}",  # Year 2024
        r"Năm\s+\d{4}",  # Năm 2024
        r"\d{4}\s*\(CY\)",  # 2024 (CY)
        r"\d{4}\s*\(PY\)",  # 2023 (PY)
    ]

    # Currency symbol patterns
    CURRENCY_PATTERNS = [
        r"VND",
        r"USD",
        r"EUR",
        r"₫",
        r"\$",
        r"€",
        r"VNĐ",
        r"Đồng",
        r"VNĐ",
        r"VND\s*\(\d{4}\)",  # VND (2024)
    ]

    # Financial term patterns (case-insensitive)
    FINANCIAL_TERMS = [
        "current year",
        "prior year",
        "năm hiện tại",
        "năm trước",
        "cy",
        "py",
        "năm nay",
        "năm trước",
        "năm báo cáo",
        "năm trước đó",
        "current period",
        "prior period",
        "kỳ hiện tại",
        "kỳ trước",
    ]

    @staticmethod
    def detect_financial_columns_advanced(
        df: pd.DataFrame,
    ) -> Tuple[Optional[str], Optional[str]]:
        """
        Detect current year and prior year columns with enhanced patterns.

        Uses multiple detection strategies:
        1. Year pattern matching (YYYY, CY2024, etc.)
        2. Financial term matching (Current Year, Năm hiện tại, etc.)
        3. Position-based fallback (last two columns)

        Args:
            df: DataFrame with table data (should have header row set)

        Returns:
            Tuple[Optional[str], Optional[str]]: (current_year_col, prior_year_col)
        """
        if df.empty or len(df.columns) < 2:
            return None, None

        columns = [str(c).strip() for c in df.columns]
        column_lower = [c.lower() for c in columns]

        # Strategy 1: Year pattern matching
        year_matches = []
        for idx, col in enumerate(columns):
            for pattern in ColumnDetector.YEAR_PATTERNS:
                if re.search(pattern, col, re.IGNORECASE):
                    # Extract year from match
                    year_match = re.search(r"\d{4}", col)
                    if year_match:
                        year = int(year_match.group())
                        year_matches.append((idx, col, year))

        # Sort by year (descending) to get current year first
        if year_matches:
            year_matches.sort(key=lambda x: x[2], reverse=True)
            if len(year_matches) >= 2:
                return year_matches[0][1], year_matches[1][1]
            elif len(year_matches) == 1:
                # Only one year found, use it as current year
                cur_col = year_matches[0][1]
                # Try to find prior year in adjacent columns
                cur_idx = year_matches[0][0]
                if cur_idx > 0:
                    prior_col = columns[cur_idx - 1]
                    return cur_col, prior_col

        # Strategy 2: Financial term matching
        cur_year_terms = [
            "current year",
            "cy",
            "năm hiện tại",
            "năm nay",
            "current period",
            "kỳ hiện tại",
        ]
        prior_year_terms = ["prior year", "py", "năm trước", "prior period", "kỳ trước"]

        cur_col_candidate = None
        prior_col_candidate = None

        for idx, col_lower in enumerate(column_lower):
            for term in cur_year_terms:
                if term in col_lower:
                    cur_col_candidate = columns[idx]
                    break
            for term in prior_year_terms:
                if term in col_lower:
                    prior_col_candidate = columns[idx]
                    break

        if cur_col_candidate and prior_col_candidate:
            return cur_col_candidate, prior_col_candidate

        # Strategy 3: Position-based fallback (last two columns)
        # This matches the original behavior
        if len(columns) >= 2:
            return columns[-2], columns[-1]

        return None, None

    @staticmethod
    def detect_code_column(df: pd.DataFrame) -> Optional[str]:
        """
        Detect code column in financial table.

        Args:
            df: DataFrame with table data

        Returns:
            Optional[str]: Column name containing codes, or None
        """
        columns = [str(c).strip() for c in df.columns]
        column_lower = [c.lower() for c in columns]

        # Look for exact match first
        for col in column_lower:
            if col == "code":
                return columns[column_lower.index(col)]

        # Look for partial match
        for idx, col_lower in enumerate(column_lower):
            if "code" in col_lower or "mã" in col_lower:
                return columns[idx]

        return None

    @staticmethod
    def detect_note_column(df: pd.DataFrame) -> Optional[str]:
        """
        Detect note column in financial table.

        Args:
            df: DataFrame with table data

        Returns:
            Optional[str]: Column name containing notes, or None
        """
        columns = [str(c).strip() for c in df.columns]
        column_lower = [c.lower() for c in columns]

        # Look for exact match first
        for col in column_lower:
            if col == "note":
                return columns[column_lower.index(col)]

        # Look for partial match
        note_terms = ["note", "notes", "ghi chú", "chú thích"]
        for idx, col_lower in enumerate(column_lower):
            for term in note_terms:
                if term in col_lower:
                    return columns[idx]

        return None

    @staticmethod
    def has_year_pattern(column_name: str) -> bool:
        """
        Check if column name contains a year pattern.

        Args:
            column_name: Column name to check

        Returns:
            bool: True if year pattern is found
        """
        for pattern in ColumnDetector.YEAR_PATTERNS:
            if re.search(pattern, str(column_name), re.IGNORECASE):
                return True
        return False

    @staticmethod
    def extract_year_from_column(column_name: str) -> Optional[int]:
        """
        Extract year value from column name if present.

        Args:
            column_name: Column name to extract year from

        Returns:
            Optional[int]: Year value if found, None otherwise
        """
        year_match = re.search(r"\d{4}", str(column_name))
        if year_match:
            try:
                return int(year_match.group())
            except ValueError:
                return None
        return None
