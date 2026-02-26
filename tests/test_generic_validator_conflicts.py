from unittest.mock import MagicMock

import pytest

from quality_audit.core.validators.base_validator import ValidationResult
from quality_audit.core.validators.generic_validator import GenericTableValidator
from quality_audit.utils.formatters import (
    GREEN_FONT,
    RED_FILL,
    apply_crossref_marks,
)


class TestGenericValidatorConflicts:
    def test_deduplicate_marks_priority(self):
        """Test that FAIL marks prioritize over PASS marks at same position."""
        validator = GenericTableValidator()

        marks = [
            {"row": 1, "col": 1, "ok": True, "comment": "Should be removed"},
            {"row": 1, "col": 1, "ok": False, "comment": "Should stay"},
            {"row": 2, "col": 2, "ok": True, "comment": "Should stay (no conflict)"},
        ]
        cross_ref_marks = []

        cleaned_marks, _ = validator._deduplicate_marks(
            marks, cross_ref_marks, is_table_fail=False
        )

        # Expecting row 1 col 1 to be False, row 2 col 2 to be True
        assert len(cleaned_marks) == 2
        mark_1_1 = next(m for m in cleaned_marks if m["row"] == 1 and m["col"] == 1)
        assert mark_1_1["ok"] is False

    def test_deduplicate_strip_pass_on_fail(self):
        """Test that PASS marks are stripped if is_table_fail is True."""
        validator = GenericTableValidator()

        marks = [
            {"row": 1, "col": 1, "ok": True, "comment": "Pass"},
            {"row": 2, "col": 2, "ok": False, "comment": "Fail"},
        ]

        cleaned_marks, _ = validator._deduplicate_marks(marks, [], is_table_fail=True)

        assert len(cleaned_marks) == 1
        assert cleaned_marks[0]["ok"] is False
        assert cleaned_marks[0]["row"] == 2

    def test_deduplicate_cross_ref_conflict(self):
        """Test conflict between validation mark and cross-ref mark."""
        validator = GenericTableValidator()

        marks = [{"row": 1, "col": 1, "ok": False, "comment": "Fail Mark"}]
        cross_ref_marks = [{"row": 1, "col": 1, "ok": True, "comment": "Pass CrossRef"}]

        # Mark (Fail) vs CrossRef (Pass) -> Mark should win (via priority logic in dedupe)
        # _deduplicate_marks returns separate lists, but cross_ref should be filtered out if conflict

        c_marks, c_cross = validator._deduplicate_marks(
            marks, cross_ref_marks, is_table_fail=False
        )

        assert len(c_marks) == 1
        assert c_marks[0]["ok"] is False
        # Cross ref mark should be removed because pos (1,1) is occupied by higher priority (Fail)
        assert len(c_cross) == 0

    def test_deduplicate_cross_ref_fail_vs_validation_pass(self):
        """Test conflict: Validation Pass vs CrossRef Fail -> CrossRef Fail wins."""
        validator = GenericTableValidator()

        marks = [{"row": 1, "col": 1, "ok": True, "comment": "Pass Mark"}]
        cross_ref_marks = [
            {"row": 1, "col": 1, "ok": False, "comment": "Fail CrossRef"}
        ]

        c_marks, c_cross = validator._deduplicate_marks(
            marks, cross_ref_marks, is_table_fail=False
        )

        # Validation Pass should be REMOVED
        assert len(c_marks) == 0

        # CrossRef Fail should be RED
        assert len(c_cross) == 1
        assert c_cross[0]["ok"] is False


class TestValidationResultDefensive:
    def test_init_strips_pass_on_fail(self):
        """Test ValidationResult automatically strips PASS marks if status_enum is FAIL."""
        marks = [{"row": 1, "col": 1, "ok": True}, {"row": 2, "col": 2, "ok": False}]
        cross_ref_marks = [
            {"row": 3, "col": 3, "ok": True},  # Should be removed
            {"row": 4, "col": 4, "ok": False},  # Should stay
        ]

        result = ValidationResult(
            status="FAIL: Some error",
            marks=marks,
            cross_ref_marks=cross_ref_marks,
            status_enum="FAIL",
        )

        # Only the False mark should remain in marks
        assert len(result.marks) == 1
        assert result.marks[0]["ok"] is False

        # Only the False mark should remain in cross_ref_marks
        assert len(result.cross_ref_marks) == 1
        assert result.cross_ref_marks[0]["ok"] is False


class TestFormatterSafeguards:
    def test_apply_crossref_skips_red_fill(self):
        """Test that apply_crossref_marks does not overwrite RED_FILL."""
        mock_ws = MagicMock()
        mock_cell = MagicMock()

        # Setup cell to behave like it has RED_FILL
        mock_cell.fill.start_color.rgb = RED_FILL.start_color.rgb
        mock_cell.fill.end_color.rgb = RED_FILL.end_color.rgb
        mock_cell.fill.fill_type = RED_FILL.fill_type

        mock_ws.cell.return_value = mock_cell

        marks = [
            {"row": 0, "col": 0, "ok": True}
        ]  # Pass cross-ref mark attempting to write "PASS"

        # Mock _dfpos_to_excel
        with pytest.MonkeyPatch.context() as m:
            m.setattr(
                "quality_audit.utils.formatters._dfpos_to_excel",
                lambda r, c: (r + 1, c + 1),
            )

            apply_crossref_marks(mock_ws, marks)

            # Since cell is detected as RED, apply_crossref_marks should NOT set font/value
            # We check that font was NOT set to GREEN_FONT
            assert mock_cell.font != GREEN_FONT
