"""
Numeric processing utilities for financial data validation.
"""

import re
from typing import Any, Dict, List, Optional, Union

import pandas as pd

from ..config.constants import TOTALS_TOLERANCE_ABS, TOTALS_TOLERANCE_REL
from ..config.feature_flags import get_feature_flags


def normalize_numeric_column(value: Any) -> Union[float, Any]:
    """
    Convert string numbers to float, handling commas, parentheses, and special characters.

    Args:
        value: Input value to convert

    Returns:
        Union[float, Any]: Converted float value or original value if conversion fails
    """
    flags = get_feature_flags()
    if not flags.get("robust_numeric_parsing", True):
        if isinstance(value, str):
            # Remove commas, convert parentheses to negative sign
            value = value.replace(",", "").replace("(", "-").replace(")", "")
        return pd.to_numeric(value, errors="coerce")

    if isinstance(value, str):
        s = value.strip()
        if not s:
            return pd.to_numeric(s, errors="coerce")

        # Normalize whitespace and common dash placeholders
        s = (
            s.replace("\u00a0", " ")  # NBSP
            .replace("\u202f", " ")  # NNBSP (thin space)
            .replace("\u2009", " ")  # thin space
            .replace("\u2212", "-")  # minus
            # Ticket-5: Strip zero-width characters
            .replace("\u200b", "")  # zero-width space
            .replace("\u200c", "")  # zero-width non-joiner
            .replace("\u200d", "")  # zero-width joiner
            .replace("\ufeff", "")  # BOM / zero-width no-break space
        )
        s = re.sub(r"\s+", " ", s)

        # Treat dash-only placeholders as NaN
        if re.fullmatch(r"[-–—]+", s):
            return pd.to_numeric(pd.NA, errors="coerce")

        # Parentheses negative: (123) -> -123
        if s.startswith("(") and s.endswith(")"):
            s = "-" + s[1:-1].strip()

        # Remove currency/unit suffixes commonly seen in headers/cells
        # Keep digits, separators, sign.
        s = re.sub(r"[A-Za-z\u00c0-\u024f'’\"₫$€]+", "", s)
        s = s.strip()

        # Ticket-5: Trailing minus sign: "1,000 -" or "1000-" -> "-1,000"
        if s.endswith("-") and not s.startswith("-"):
            s = "-" + s[:-1].strip()

        # Handle percentage values: "100%" -> 100.0, "49.5%" -> 49.5
        if s.endswith("%"):
            s = s[:-1].strip()

        # Normalize thousands/decimal separators:
        # - If both '.' and ',' exist, assume last separator is decimal and remove the other as thousands.
        # - If only one separator repeats, treat it as thousands separator.
        if "." in s and "," in s:
            last_dot = s.rfind(".")
            last_comma = s.rfind(",")
            if last_dot > last_comma:
                # dot decimal, commas thousands
                s = s.replace(",", "")
            else:
                # comma decimal, dots thousands
                s = s.replace(".", "").replace(",", ".")
        else:
            # Remove spaces as thousands separators
            s = s.replace(" ", "")
            # Single comma: decide decimal vs thousands
            if s.count(",") == 1 and "." not in s:
                left, right = s.split(",", 1)
                # Thousands pattern: 1,234 or -100,000
                if (
                    right.isdigit()
                    and len(right) == 3
                    and left.replace("-", "").isdigit()
                ):
                    s = left + right
                # Otherwise treat comma as decimal separator: 123,45 -> 123.45
                else:
                    s = left + "." + right
            # If multiple commas, treat as thousands separators
            if s.count(",") > 1 and "." not in s:
                s = s.replace(",", "")
            # If multiple dots, treat as thousands separators
            if s.count(".") > 1 and "," not in s:
                s = s.replace(".", "")

        # Final cleanup
        s = s.replace("(", "").replace(")", "")
        return pd.to_numeric(s, errors="coerce")

    return pd.to_numeric(value, errors="coerce")


def is_year_like_value(value: Any) -> bool:
    """
    Return True if the value looks like a calendar year (19xx/20xx).
    Used to exclude year values from amount-column sums (numeric leakage guard).
    """
    try:
        v = normalize_numeric_column(value)
        if pd.isna(v):
            return False
        f = float(v)
        if f != int(f):
            return False
        return 1900 <= f <= 2100
    except (TypeError, ValueError):
        return False


def validate_percentage(value: float, allow_over_100: bool = True) -> bool:
    """Validate if value is a valid percentage.

    Args:
        value: Percentage value (0-100 scale, not decimal)
        allow_over_100: Whether to allow percentages > 100%

    Returns:
        bool: True if valid percentage
    """
    if pd.isna(value):
        return False
    if allow_over_100:
        return value >= 0  # Allow any non-negative
    return 0 <= value <= 100


def parse_numeric(value: Any) -> float:
    """
    Parse numeric value with fallback to zero for NaN.
    Includes input validation to prevent injection attacks.

    Args:
        value: Value to parse

    Returns:
        float: Parsed numeric value or 0.0
    """
    # Input validation: limit string length to prevent DoS
    if isinstance(value, str) and len(value) > 1000:
        return 0.0

    val = normalize_numeric_column(value)

    # Bounds checking: prevent extremely large values that could cause overflow
    if pd.notna(val):
        numeric_val = float(val)
        # Reasonable bounds for financial data (trillion range)
        max_abs_value = 1e15
        if abs(numeric_val) > max_abs_value:
            return 0.0
        return numeric_val

    return 0.0


def format_currency(value: float, decimals: int = 0) -> str:
    """
    Format numeric value as currency string.

    Args:
        value: Numeric value to format
        decimals: Number of decimal places

    Returns:
        str: Formatted currency string
    """
    try:
        return f"{value:,.{decimals}f}"
    except (ValueError, TypeError):
        return str(value)


def safe_divide(numerator: float, denominator: float, default: float = 0.0) -> float:
    """
    Safe division with zero denominator handling.

    Args:
        numerator: Numerator value
        denominator: Denominator value
        default: Default value to return if denominator is zero

    Returns:
        float: Division result or default value
    """
    try:
        return numerator / denominator if denominator != 0 else default
    except (ZeroDivisionError, TypeError):
        return default


def calculate_percentage_change(current: float, previous: float) -> float:
    """
    Calculate percentage change between two values.

    Args:
        current: Current period value
        previous: Previous period value

    Returns:
        float: Percentage change
    """
    if previous == 0:
        return float("inf") if current > 0 else 0.0

    try:
        return ((current - previous) / abs(previous)) * 100
    except (ZeroDivisionError, TypeError):
        return 0.0


def round_to_precision(value: float, precision: int = 2) -> float:
    """
    Round value to specified decimal precision.

    Args:
        value: Value to round
        precision: Decimal places

    Returns:
        float: Rounded value
    """
    try:
        return round(value, precision)
    except (TypeError, ValueError):
        return value


def compare_amounts(
    expected: float,
    actual: float,
    abs_tol: Optional[float] = None,
    rel_tol: Optional[float] = None,
) -> tuple[bool, float, float, str]:
    """
    Compare expected vs actual amount with config tolerance (abs and/or rel).

    Uses same rule as base_validator Rule C: pass if abs(diff) <= max(abs_tol, rel_tol * ref)
    where ref = max(|expected|, |actual|, 1.0).

    Returns:
        (is_ok, abs_delta, rel_delta, tolerance_used)
        - tolerance_used: "abs" | "rel" (which bound was applied for reporting)
    """
    if abs_tol is None:
        abs_tol = TOTALS_TOLERANCE_ABS
    if rel_tol is None:
        rel_tol = TOTALS_TOLERANCE_REL

    if pd.isna(expected) or pd.isna(actual):
        return (False, float("nan"), float("nan"), "none")

    expected = float(expected)
    actual = float(actual)
    diff = expected - actual
    abs_d = abs(diff)
    ref = max(abs(expected), abs(actual), 1.0)
    tol_abs = abs_tol
    tol_rel = rel_tol * ref
    tol = max(tol_abs, tol_rel)
    is_ok = abs_d <= tol
    rel_d = (abs_d / ref * 100.0) if ref else 0.0
    tolerance_used = "abs" if tol_abs >= tol_rel else "rel"
    return (is_ok, abs_d, rel_d, tolerance_used)


def validate_numeric_range(
    value: float, min_val: Optional[float] = None, max_val: Optional[float] = None
) -> bool:
    """
    Validate if numeric value is within specified range.

    Args:
        value: Value to validate
        min_val: Minimum allowed value (None for no minimum)
        max_val: Maximum allowed value (None for no maximum)

    Returns:
        bool: True if value is within range
    """
    if not isinstance(value, (int, float)) or pd.isna(value):
        return False

    if min_val is not None and value < min_val:
        return False

    return not (max_val is not None and value > max_val)


def compute_numeric_evidence_score(
    df: pd.DataFrame,
    candidate_columns: Optional[List[str]] = None,
    sample_rows: int = 20,
) -> Dict[str, Any]:
    """
    Compute numeric evidence score for a table: parseable_ratio and digit_presence_ratio
    per candidate column, and a table-level numeric_evidence_score (max across candidates).

    Used to gate PASS: tables with no numeric data (score < 0.25) must not PASS.

    Args:
        df: DataFrame (data rows; header may be in row 0 or already promoted).
        candidate_columns: Columns to evaluate; if None, use all columns in df.
        sample_rows: Max rows to sample for ratio computation (default 20).

    Returns:
        Dict with:
            - numeric_col_candidates: list of column names evaluated
            - per_column: dict col_name -> {parseable_ratio, digit_presence_ratio}
            - numeric_evidence_score: float, max across candidates of max(parseable_ratio, digit_presence_ratio)
            - numeric_parse_rate: same as numeric_evidence_score (alias for reporting)
            - numeric_cell_ratio: average digit_presence across candidates (optional for reporting)
    """
    if df.empty:
        return {
            "numeric_col_candidates": [],
            "per_column": {},
            "numeric_evidence_score": 0.0,
            "numeric_parse_rate": 0.0,
            "numeric_cell_ratio": 0.0,
        }

    cols = candidate_columns if candidate_columns is not None else list(df.columns)
    cols = [c for c in cols if c in df.columns]
    if not cols:
        return {
            "numeric_col_candidates": [],
            "per_column": {},
            "numeric_evidence_score": 0.0,
            "numeric_parse_rate": 0.0,
            "numeric_cell_ratio": 0.0,
        }

    n_sample = min(sample_rows, len(df))
    sample_df = df.iloc[:n_sample]

    per_column: Dict[str, Dict[str, float]] = {}
    max_score = 0.0
    sum_digit_ratio = 0.0

    for col in cols:
        series = sample_df[col]
        non_empty = series.astype(str).str.strip()
        non_empty_mask = (non_empty != "") & (non_empty.str.lower() != "nan")
        n_non_empty = int(non_empty_mask.sum())
        if n_non_empty == 0:
            per_column[col] = {"parseable_ratio": 0.0, "digit_presence_ratio": 0.0}
            continue

        parsed = series.astype(object).map(normalize_numeric_column)
        parseable_count = int(parsed.notna().sum())
        parseable_ratio = float(parseable_count / n_non_empty)

        has_digit = series.astype(str).str.contains(r"\d", regex=True, na=False)
        digit_count = int(has_digit.sum())
        digit_presence_ratio = float(digit_count / n_non_empty)

        per_column[col] = {
            "parseable_ratio": parseable_ratio,
            "digit_presence_ratio": digit_presence_ratio,
        }
        col_score = max(parseable_ratio, digit_presence_ratio)
        max_score = max(max_score, col_score)
        sum_digit_ratio += digit_presence_ratio

    n_cols = len(cols)
    avg_cell_ratio = sum_digit_ratio / n_cols if n_cols else 0.0

    return {
        "numeric_col_candidates": cols,
        "per_column": per_column,
        "numeric_evidence_score": max_score,
        "numeric_parse_rate": max_score,
        "numeric_cell_ratio": avg_cell_ratio,
    }
