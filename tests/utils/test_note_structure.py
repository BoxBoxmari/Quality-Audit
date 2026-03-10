"""
Unit tests for NOTE structure analyzer (analyze_note_table).
"""

import pandas as pd

from quality_audit.utils.note_structure import (
    RowType,
    _classify_row_type,
    _detect_amount_cols,
    _detect_label_col,
    _normalize_text,
    analyze_note_table,
)


class TestNormalizeText:
    def test_empty_nan(self):
        assert _normalize_text("") == ""
        assert _normalize_text(None) == ""
        assert _normalize_text(float("nan")) == ""

    def test_lower_strip(self):
        assert _normalize_text("  Opening balance  ") == "opening balance"


class TestClassifyRowType:
    def test_opening(self):
        assert _classify_row_type("Opening balance") == RowType.OPENING
        assert _classify_row_type("Số dư đầu kỳ") == RowType.OPENING

    def test_closing(self):
        assert _classify_row_type("Closing balance") == RowType.CLOSING
        assert _classify_row_type("Số dư cuối năm") == RowType.CLOSING

    def test_movement(self):
        assert _classify_row_type("Depreciation") == RowType.MOVEMENT
        assert _classify_row_type("Additions") == RowType.MOVEMENT

    def test_total_like(self):
        assert _classify_row_type("Total") == RowType.TOTAL_LIKE
        assert _classify_row_type("Tổng") == RowType.TOTAL_LIKE

    def test_blank(self):
        assert _classify_row_type("", has_numeric=False) == RowType.BLANK
        assert _classify_row_type("", has_numeric=True) == RowType.OTHER
        assert _classify_row_type("   ", has_numeric=False) == RowType.BLANK


class TestDetectLabelCol:
    def test_text_column_wins(self):
        df = pd.DataFrame(
            {
                "Label": ["A", "B", "C", "D"],
                "Col1": [1, 2, 3, 4],
                "Col2": [10, 20, 30, 40],
            }
        )
        assert _detect_label_col(df) == "Label"

    def test_empty_returns_none(self):
        assert _detect_label_col(pd.DataFrame()) is None


class TestDetectAmountCols:
    def test_numeric_columns_included(self):
        df = pd.DataFrame(
            {"Label": ["A", "B"], "Cost": [100, 200], "AD": [10, 20], "NBV": [90, 180]}
        )
        cols = _detect_amount_cols(df, "Label")
        assert "Cost" in cols
        assert "AD" in cols
        assert "NBV" in cols
        assert "Label" not in cols

    def test_label_excluded(self):
        df = pd.DataFrame({"L": ["x", "y"], "V": [1, 2]})
        assert _detect_amount_cols(df, "L") == ["V"]


class TestAnalyzeNoteTable:
    def test_empty_df(self):
        result = analyze_note_table(pd.DataFrame(), "Note", "017")
        assert result.label_col is None
        assert result.amount_cols == []
        assert result.segments == []
        assert result.is_movement_table is False
        assert result.confidence == 0.0

    def test_movement_table_detection(self):
        df = pd.DataFrame(
            {
                "Item": [
                    "Opening balance",
                    "Additions",
                    "Disposals",
                    "Depreciation",
                    "Closing balance",
                ],
                "Cost": [1000, 200, 50, 0, 1150],
                "AD": [100, 50, 10, 80, 220],
            }
        )
        result = analyze_note_table(df, "Tangible fixed assets", "017")
        assert result.label_col == "Item"
        assert "Cost" in result.amount_cols
        assert "AD" in result.amount_cols
        assert result.is_movement_table is True
        assert len(result.segments) >= 1
        assert result.segments[0].ob_row_idx is not None
        assert result.segments[0].cb_row_idx is not None
        assert len(result.segments[0].movement_rows) >= 1

    def test_row_types_populated(self):
        df = pd.DataFrame({"L": ["Opening", "Additions", "Total"], "V": [10, 5, 15]})
        result = analyze_note_table(df, "Note", None)
        assert len(result.row_types) == 3
        assert result.row_types[0] == RowType.OPENING
        assert result.row_types[2] == RowType.TOTAL_LIKE
