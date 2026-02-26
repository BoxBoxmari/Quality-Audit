"""
Excel formatting and cell manipulation utilities.
"""

from typing import Any, Dict, List, Tuple, cast

from openpyxl.comments import Comment

from ..config.constants import GREEN_FILL, GREEN_FONT, RED_FILL, RED_FONT, RIGHT_ALIGN


def shorten_sheet_name(name: str, max_length: int = 20) -> str:
    """
    Shorten sheet name to avoid Excel length limits and remove special characters.

    Args:
        name: Original sheet name
        max_length: Maximum allowed length

    Returns:
        str: Cleaned and shortened sheet name
    """
    from ..config.constants import _SHEET_NAME_CLEAN_RE

    name = _SHEET_NAME_CLEAN_RE.sub("_", str(name))
    return name[:max_length]


def _dfpos_to_excel(row_idx_0based: int, col_idx_0based: int) -> Tuple[int, int]:
    """
    Convert DataFrame position to Excel position.

    DataFrame rows start from header at index 0, Excel rows start from 1.
    DataFrame columns start from 0, Excel columns start from 1.

    Args:
        row_idx_0based: DataFrame row index (0-based)
        col_idx_0based: DataFrame column index (0-based)

    Returns:
        Tuple[int, int]: (excel_row, excel_col)
    """
    return row_idx_0based + 2, col_idx_0based + 1


def is_red_fill(cell) -> bool:
    """
    Check if cell has red fill color.

    Args:
        cell: OpenPyXL cell object

    Returns:
        bool: True if cell has red fill
    """
    fill = cell.fill
    return cast(
        bool,
        (
            fill.start_color.rgb == RED_FILL.start_color.rgb
            and fill.end_color.rgb == RED_FILL.end_color.rgb
            and fill.fill_type == RED_FILL.fill_type
        ),
    )


def apply_cell_marks(
    ws, marks: List[Dict], start_row: int = 0, start_col: int = 0
) -> None:
    """
    Apply cell marks (colors) to worksheet based on validation results.

    Args:
        ws: OpenPyXL worksheet
        marks: List of mark dictionaries with 'row', 'col', 'ok', 'comment' keys
        start_row: Row offset for positioning
        start_col: Column offset for positioning
    """
    for mark in marks:
        r, c = _dfpos_to_excel(mark["row"], mark["col"])
        cell = ws.cell(row=r + start_row, column=c + start_col)

        if mark.get("ok") is True:
            if not is_red_fill(cell):  # Only apply green if not already red
                cell.fill = GREEN_FILL
        elif mark.get("ok") is False:
            cell.fill = RED_FILL

        # Add comment for error cells
        if mark.get("comment"):
            try:
                # Merge with existing comment if present
                if cell.comment:
                    new_text = cell.comment.text + "\n" + str(mark["comment"])
                else:
                    new_text = str(mark["comment"])
                cell.comment = Comment(text=new_text, author="AutoCheck")
            except Exception:
                # Skip comment if it fails
                pass


def apply_crossref_marks(
    ws, marks: List[Dict], start_row: int = 0, start_col: int = 0
) -> None:
    """
    Apply cross-reference marks with right alignment and color coding.

    Args:
        ws: OpenPyXL worksheet
        marks: List of mark dictionaries
        start_row: Row offset
        start_col: Column offset
    """
    for mark in marks:
        r, c = _dfpos_to_excel(mark["row"], mark["col"])
        cell = ws.cell(row=r + start_row, column=c + start_col)
        cell.alignment = RIGHT_ALIGN  # Right align for cross-ref cells

        # Safeguard: never overwrite an already-red cell (priority to validation FAIL fill)
        if is_red_fill(cell):
            continue

        # Set font color and value based on status
        if mark.get("ok") is True:
            cell.font = GREEN_FONT
            cell.value = "PASS"
        elif mark.get("ok") is False:
            cell.font = RED_FONT
            cell.value = "FAIL"

            # Add error comment
            try:
                if cell.comment:
                    new_text = cell.comment.text + "\n" + str(mark["comment"])
                else:
                    new_text = str(mark["comment"])
                cell.comment = Comment(text=new_text, author="AutoCheck")
            except Exception:
                pass


def sanitize_excel_value(value: Any) -> Any:
    """
    Sanitize values before writing to Excel to prevent formula injection.

    Only sanitizes string values that start with dangerous characters.
    Numeric values are left unchanged to preserve formatting.

    Args:
        value: Value to sanitize

    Returns:
        Any: Sanitized value safe for Excel
    """
    # Only sanitize strings
    if not isinstance(value, str):
        return value

    # Strip whitespace for checking
    stripped_value = value.strip()

    # If it's a valid number, don't sanitize
    try:
        float(stripped_value.replace(",", "").replace("(", "-").replace(")", ""))
        return value  # Return original value to preserve as number
    except (ValueError, TypeError):
        pass

    # Escape dangerous characters that could be interpreted as formulas
    dangerous_chars = ["=", "+", "-", "@", "\t", "\r"]

    for char in dangerous_chars:
        if stripped_value.startswith(char):
            return f"'{value}"  # Prefix with single quote to force text interpretation

    return value
