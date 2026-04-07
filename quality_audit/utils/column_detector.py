"""
Advanced column detection utilities for financial tables.

Provides enhanced pattern matching for detecting financial columns,
including year patterns, currency symbols, and multi-language support.
"""

import logging
import re
from enum import Enum
from typing import Dict, Optional, Tuple

import pandas as pd

from .numeric_utils import compute_numeric_evidence_score

logger = logging.getLogger(__name__)


class ColumnType(Enum):
    """Column classification for financial tables (Phase 5)."""

    TEXT = "TEXT"
    CODE = "CODE"
    NUMERIC_CY = "NUMERIC_CY"
    NUMERIC_PY = "NUMERIC_PY"
    OTHER = "OTHER"


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

        # Deduplicate matches per column (same column can match multiple patterns)
        if year_matches:
            by_col: dict[int, tuple[int, str, int]] = {}
            for tup in year_matches:
                i, c, y = tup
                # Keep the max year for that column (should be identical, but defensive)
                if i not in by_col or y > by_col[i][2]:
                    by_col[i] = tup
            year_matches = list(by_col.values())

        # Sort by year (descending) to get current year first
        if year_matches:
            year_matches.sort(key=lambda x: x[2], reverse=True)
            if len(year_matches) >= 2:
                return year_matches[0][1], year_matches[1][1]
            elif len(year_matches) == 1:
                # Only one year found, use it as current year
                cur_col = year_matches[0][1]
                # No reliable prior-year inference from adjacency (often "Code"/"Account").
                return cur_col, None

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

        # Strategy 3: Evaluate last K columns by numeric evidence; return best adjacent pair or (None, None)
        if len(columns) >= 2:
            # Prefer columns that match year pattern
            year_cols = [
                c
                for c in columns
                if re.search(r"(20\d{2}|CY|PY|Năm)", str(c), re.IGNORECASE)
            ]
            if len(year_cols) >= 2:
                # If there are exactly two or more year cols, use the last two found (most likely the actual periods, not a description)
                logger.info(
                    "Strategy 3: using year pattern columns %s, %s",
                    year_cols[-2],
                    year_cols[-1],
                )
                return year_cols[-2], year_cols[-1]
            elif len(year_cols) == 1:
                logger.info(
                    "Strategy 3: only one year pattern column found %s", year_cols[0]
                )
                return year_cols[0], None

            k = min(5, len(columns))
            last_k = list(columns[-k:])
            evidence = compute_numeric_evidence_score(
                df, candidate_columns=last_k, sample_rows=20
            )
            per_col = evidence.get("per_column") or {}
            threshold = (
                0.2  # Group 1/3/4: lowered from 0.25 to reduce NO_NUMERIC_EVIDENCE
            )
            # Per-column score = max(parseable_ratio, digit_presence_ratio)
            scores = {}
            for col in last_k:
                info = per_col.get(col) or {}
                scores[col] = max(
                    float(info.get("parseable_ratio", 0)),
                    float(info.get("digit_presence_ratio", 0)),
                )
            # Ticket 3: Semantic header boost / penalty
            currency_kw = (
                "vnd",
                "usd",
                "eur",
                "triệu",
                "million",
                "dong",
                "đồng",
            )
            artifact_kw = [
                r"_1",
                r"_2",
                r"_3",
                r"_4",
                r"_5",
                r"Unnamed",
                r"Empty",
                r"Column",
            ]

            for col in last_k:
                header_lower = str(col).lower()
                if ColumnDetector.has_year_pattern(str(col)):
                    scores[col] += 0.3  # Year pattern boost
                if any(kw in header_lower for kw in currency_kw):
                    scores[col] += 0.2  # Currency unit boost
                if (
                    "%" in header_lower
                    or "percent" in header_lower
                    or "tỷ lệ" in header_lower
                ):
                    scores[col] -= 0.4  # Percentage penalty

                # Penalize structural artifacts (e.g. padding columns like Amount_2)
                if any(re.search(pat, str(col), re.IGNORECASE) for pat in artifact_kw):
                    scores[col] -= 0.3

            # Rightmost adjacent pair (prior_col, cur_col) with both >= threshold
            for i in range(len(last_k) - 1, 0, -1):
                left_col, right_col = last_k[i - 1], last_k[i]
                if (
                    scores.get(left_col, 0) >= threshold
                    and scores.get(right_col, 0) >= threshold
                ):
                    logger.info(
                        "Strategy 3: selected adjacent pair %s, %s (scores %.2f, %.2f)",
                        left_col,
                        right_col,
                        scores[left_col],
                        scores[right_col],
                    )
                    return left_col, right_col
            # Fallback (Group 1/4): last two columns with score >= 0.1 as CY/PY
            if len(columns) >= 2:
                # Find the two right-most columns with score >= 0.1
                valid_cols = [c for c in last_k if scores.get(c, 0) >= 0.1]
                if len(valid_cols) >= 2:
                    logger.info(
                        "Strategy 3 fallback: using columns %s, %s (scores %.2f, %.2f)",
                        valid_cols[-2],
                        valid_cols[-1],
                        scores.get(valid_cols[-2], 0),
                        scores.get(valid_cols[-1], 0),
                    )
                    return valid_cols[-2], valid_cols[-1]
            logger.info(
                "Strategy 3: no valid numeric pairs found in last %d columns",
                k,
            )
            return None, None
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

    @staticmethod
    def classify_columns(df: pd.DataFrame) -> Dict[str, ColumnType]:
        """
        Classify each column as TEXT, CODE, NUMERIC_CY, NUMERIC_PY, or OTHER.

        Phase 5: Used by totals detection and validators to identify amount columns
        and exclude code/text columns from sum checks.

        Args:
            df: DataFrame with table data (header row as columns).

        Returns:
            Dict mapping column name -> ColumnType.
        """
        if df.empty:
            return {}
        columns = [str(c).strip() for c in df.columns]
        result: Dict[str, ColumnType] = {}
        code_col = ColumnDetector.detect_code_column(df)
        cur_col, prior_col = ColumnDetector.detect_financial_columns_advanced(df)
        note_col = ColumnDetector.detect_note_column(df)
        for col in columns:
            if code_col and col == code_col:
                result[col] = ColumnType.CODE
            elif note_col and col == note_col:
                result[col] = ColumnType.TEXT
            elif cur_col and col == cur_col:
                result[col] = ColumnType.NUMERIC_CY
            elif prior_col and col == prior_col:
                result[col] = ColumnType.NUMERIC_PY
            elif ColumnDetector.has_year_pattern(col):
                # Year-like but not chosen as CY/PY (e.g. third period)
                result[col] = ColumnType.OTHER
            else:
                # Description, label, or unidentified
                result[col] = ColumnType.TEXT
        return result
