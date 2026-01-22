"""
Excel workbook creation and writing utilities with security sanitization.
"""

from typing import Dict, List, Tuple

import pandas as pd
from openpyxl import Workbook
from openpyxl.utils import get_column_letter, quote_sheetname
from openpyxl.utils.dataframe import dataframe_to_rows
from openpyxl.worksheet.table import Table, TableStyleInfo

from ..config.constants import GREEN_FILL, INFO_FILL, RED_FILL
from ..utils.formatters import (apply_cell_marks, apply_crossref_marks,
                                sanitize_excel_value)


class ExcelWriter:
    """Handles secure Excel workbook creation and writing."""

    def __init__(self):
        """Initialize Excel writer."""
        pass

    def create_workbook(self) -> Workbook:
        """
        Create a new Excel workbook.

        Returns:
            Workbook: New OpenPyXL workbook
        """
        return Workbook()

    def write_summary_sheet(
        self, wb: Workbook, results: List[Dict], sheet_positions: List[Tuple[str, int]]
    ) -> None:
        """
        Write summary sheet with validation results and hyperlinks.

        Args:
            wb: Excel workbook
            results: List of validation results
            sheet_positions: List of (heading, start_row) tuples
        """
        ws = wb.active
        ws.title = "Tổng hợp kiểm tra"
        ws.append(["Tên bảng", "Trạng thái kiểm tra"])

        for i, (result, (heading, start_row)) in enumerate(
            zip(results, sheet_positions)
        ):
            cell = ws.cell(row=i + 2, column=1, value=heading)
            if heading in wb.sheetnames:
                quoted_name = quote_sheetname(heading)
                cell.hyperlink = f"#{quoted_name}!A1"
                cell.style = "Hyperlink"

            ws.cell(row=i + 2, column=2, value=result.get("status"))

        self._apply_status_colors(ws)

    def write_tables(
        self,
        wb: Workbook,
        table_heading_pairs: List[Tuple[pd.DataFrame, str]],
        results: List[Dict],
    ) -> List[str]:
        """
        Write all tables to individual sheets.

        Args:
            wb: Excel workbook
            table_heading_pairs: List of (table_df, heading) tuples
            results: List of validation results

        Returns:
            List[str]: List of created sheet names
        """
        sheet_names = []

        for i, ((table, heading), result) in enumerate(
            zip(table_heading_pairs, results)
        ):
            # Sanitize table data
            table = table.copy()
            table = table.map(sanitize_excel_value)

            # Create sheet name
            raw_name = heading if heading else f"Bảng {i + 1}"
            sheet_name = self._shorten_sheet_name(raw_name)

            # Ensure unique sheet name
            original_name = sheet_name
            counter = 1
            while sheet_name in wb.sheetnames:
                sheet_name = f"{original_name}_{counter}"
                counter += 1

            sheet_names.append(sheet_name)

            # Create worksheet and write data
            ws = wb.create_sheet(title=sheet_name)

            # Write DataFrame to worksheet
            for row_idx, row in enumerate(
                dataframe_to_rows(table, index=False, header=True)
            ):
                for col_idx, value in enumerate(row):
                    # Format numbers as accounting format
                    if row_idx > 0:  # Skip header row
                        try:
                            num_val = float(
                                str(value)
                                .replace(",", "")
                                .replace("(", "-")
                                .replace(")", "")
                            )
                            cell = ws.cell(
                                row=row_idx + 1, column=col_idx + 1, value=num_val
                            )
                            cell.number_format = (
                                '_(* #,##0_);_(* (#,##0);_(* "-"??_);_(@_)'
                            )
                        except (ValueError, TypeError):
                            ws.cell(row=row_idx + 1, column=col_idx + 1, value=value)
                    else:
                        ws.cell(row=row_idx + 1, column=col_idx + 1, value=value)

            # Create Excel table
            max_col = get_column_letter(ws.max_column)
            max_row = ws.max_row
            tab = Table(displayName=f"Table{i + 1}", ref=f"A1:{max_col}{max_row}")
            tab.tableStyleInfo = TableStyleInfo(
                name="TableStyleMedium9", showRowStripes=True
            )
            ws.add_table(tab)

            # Apply formatting
            apply_cell_marks(ws, result.get("marks", []))
            apply_crossref_marks(ws, result.get("cross_ref_marks", []))

            # Add status and back link
            ws.cell(row=max_row + 2, column=1, value="Trạng thái kiểm tra:")
            ws.cell(row=max_row + 2, column=2, value=result.get("status"))

            back_cell = ws.cell(row=max_row + 3, column=1, value="⬅ Quay lại Tổng hợp")
            back_cell.hyperlink = "#'Tổng hợp kiểm tra'!A1"
            back_cell.style = "Hyperlink"

        return sheet_names

    def write_tables_consolidated(
        self,
        wb: Workbook,
        table_heading_pairs: List[Tuple[pd.DataFrame, str]],
        results: List[Dict],
    ) -> List[Tuple[str, int]]:
        """
        Write all tables to a single consolidated sheet.

        Args:
            wb: Excel workbook
            table_heading_pairs: List of (table_df, heading) tuples
            results: List of validation results

        Returns:
            List[Tuple[str, int]]: List of (heading, start_row) tuples
        """
        sheet_name = "FS casting"
        ws = wb.create_sheet(title=sheet_name)
        sheet_positions = []
        current_row = 1

        for i, ((table, heading), result) in enumerate(
            zip(table_heading_pairs, results)
        ):
            # Sanitize table data
            table = table.copy()
            table.columns = table.columns.map(str)

            # Add heading
            raw_name = heading if heading else f"Bảng {i + 1}"
            sheet_positions.append((raw_name, current_row))
            ws.cell(row=current_row, column=1, value=raw_name)
            current_row += 1

            # Write table
            start_row = current_row
            start_col = 1

            for row_idx, row in enumerate(
                dataframe_to_rows(table, index=False, header=True)
            ):
                for col_idx, value in enumerate(row):
                    if row_idx == 0:
                        # Header row - no sanitization needed for headers
                        ws.cell(
                            row=current_row, column=start_col + col_idx, value=value
                        )
                    else:
                        # Data row - try numeric formatting first, then sanitize if
                        # needed
                        try:
                            # Try to parse as number first
                            num_val = float(
                                str(value)
                                .replace(",", "")
                                .replace("(", "-")
                                .replace(")", "")
                            )
                            cell = ws.cell(
                                row=current_row,
                                column=start_col + col_idx,
                                value=num_val,
                            )
                            cell.number_format = (
                                '_(* #,##0_);_(* (#,##0);_(* "-"??_);_(@_)'
                            )
                        except (ValueError, TypeError):
                            # Not a number, sanitize and write as text
                            safe_value = sanitize_excel_value(value)
                            ws.cell(
                                row=current_row,
                                column=start_col + col_idx,
                                value=safe_value,
                            )

                current_row += 1

            # Create Excel table
            end_row = current_row - 1
            end_col = start_col + len(table.columns) - 1
            table_range = f"{
                ws.cell(
                    row=start_row,
                    column=start_col).coordinate}:{
                ws.cell(
                    row=end_row,
                    column=end_col).coordinate}"
            excel_table = Table(displayName=f"Table_{i + 1}", ref=table_range)
            style = TableStyleInfo(
                name="TableStyleMedium9",
                showFirstColumn=False,
                showLastColumn=False,
                showRowStripes=True,
                showColumnStripes=False,
            )
            excel_table.tableStyleInfo = style
            ws.add_table(excel_table)

            # Apply formatting
            apply_cell_marks(ws, result.get("marks", []), start_row - 1, start_col - 1)
            apply_crossref_marks(
                ws, result.get("cross_ref_marks", []), start_row, start_col - 1
            )

            # Add status and spacing
            ws.cell(row=current_row + 1, column=1, value="Trạng thái kiểm tra:")
            ws.cell(row=current_row + 1, column=2, value=result.get("status"))

            back_cell = ws.cell(
                row=current_row + 2, column=1, value="⬅ Quay lại Tổng hợp"
            )
            back_cell.hyperlink = "#'Tổng hợp kiểm tra'!A1"
            back_cell.style = "Hyperlink"

            current_row += 4  # Add spacing between tables

        return sheet_positions

    def save_workbook(self, wb: Workbook, file_path: str) -> None:
        """
        Save workbook to file.

        Args:
            wb: Excel workbook
            file_path: Output file path
        """
        wb.save(file_path)

    def _shorten_sheet_name(self, name: str, max_length: int = 20) -> str:
        """
        Shorten sheet name for Excel compatibility.

        Args:
            name: Original name
            max_length: Maximum length

        Returns:
            str: Shortened name
        """
        from ..config.constants import _SHEET_NAME_CLEAN_RE

        name = _SHEET_NAME_CLEAN_RE.sub("_", str(name))
        return name[:max_length]

    def _apply_status_colors(self, ws) -> None:
        """
        Apply color coding to status cells.

        Args:
            ws: Worksheet to format
        """
        for row in ws.iter_rows(min_row=2, min_col=2, max_col=2):
            for cell in row:
                status_text = str(cell.value or "").lower()
                if "PASS" in status_text:
                    cell.fill = GREEN_FILL
                elif "FAIL" in status_text:
                    cell.fill = RED_FILL
                elif "WARN" in status_text:
                    cell.fill = INFO_FILL
                else:
                    cell.fill = INFO_FILL  # Default for unknown status
