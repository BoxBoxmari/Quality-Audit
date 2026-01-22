"""
Numeric processing utilities for financial data validation.
"""

from typing import Any, Union

import pandas as pd


def normalize_numeric_column(value: Any) -> Union[float, Any]:
    """
    Convert string numbers to float, handling commas, parentheses, and special characters.

    Args:
        value: Input value to convert

    Returns:
        Union[float, Any]: Converted float value or original value if conversion fails
    """
    if isinstance(value, str):
        # Remove commas, convert parentheses to negative sign
        value = value.replace(",", "").replace("(", "-").replace(")", "")
    return pd.to_numeric(value, errors="coerce")


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


def validate_numeric_range(
    value: float, min_val: float = None, max_val: float = None
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

    if max_val is not None and value > max_val:
        return False

    return True
