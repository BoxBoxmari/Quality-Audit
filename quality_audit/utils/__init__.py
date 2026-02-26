"""
Utilities package for common functionality.
"""

from .chunk_processor import ChunkProcessor
from .column_detector import ColumnDetector
from .formatters import (
    apply_cell_marks,
    apply_crossref_marks,
    sanitize_excel_value,
    shorten_sheet_name,
)
from .numeric_utils import (
    calculate_percentage_change,
    format_currency,
    normalize_numeric_column,
    parse_numeric,
    safe_divide,
)

__all__ = [
    # Formatters
    "shorten_sheet_name",
    "apply_cell_marks",
    "apply_crossref_marks",
    "sanitize_excel_value",
    # Numeric utils
    "normalize_numeric_column",
    "parse_numeric",
    "format_currency",
    "safe_divide",
    "calculate_percentage_change",
    # Column detection
    "ColumnDetector",
    # Chunk processing
    "ChunkProcessor",
]
