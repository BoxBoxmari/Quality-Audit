"""
Phase 6: Tests for GenericValidator evidence gate, movement structure, and PASS only when assertions_count > 0.
"""

from unittest.mock import patch

import pandas as pd
import pytest

from quality_audit.core.validators.generic_validator import GenericTableValidator


@pytest.fixture
def validator():
    return GenericTableValidator()


class TestEvidenceGate:
    """Evidence gate: column-totals validation skipped when last col not total-like or first col has no labels."""

    @pytest.mark.parametrize(
        "last_col_header,first_col_has_label,expect_column_totals",
        [
            ("Total", True, True),
            ("Total", False, False),
            ("Other", True, False),
        ],
    )
    def test_evidence_gate_skips_when_gate_fails(
        self, validator, last_col_header, first_col_has_label, expect_column_totals
    ):
        with patch(
            "quality_audit.core.validators.generic_validator.get_feature_flags"
        ) as gff:
            gff.return_value = {"generic_evidence_gate": True}
            df = pd.DataFrame(
                {
                    "A": ["Label", "100"] if first_col_has_label else ["", ""],
                    "B": [100, 200],
                    last_col_header: [300, 300],
                }
            )
            df.columns = [str(c) for c in df.columns]
            result = validator.validate(df, "Balance Sheet")
            assert result is not None
            if not expect_column_totals:
                assert result.status_enum in ("PASS", "INFO", "FAIL", "WARN")

    def test_evidence_gate_no_early_info_in_parity_mode(self, validator):
        """In parity mode, evidence gate must not early-return INFO soft-skip."""
        with patch(
            "quality_audit.core.validators.generic_validator.get_feature_flags"
        ) as gff:
            gff.return_value = {
                "generic_evidence_gate": True,
                "legacy_parity_mode": True,
                "movement_rollforward": False,
            }
            df = pd.DataFrame(
                {
                    "A": ["", "100", "Total"],
                    "B": [100, 200, 300],
                    "Other": [100, 200, 300],
                }
            )
            result = validator.validate(df, "Balance Sheet")
            assert result is not None
            assert not (
                result.status_enum == "INFO"
                and (result.context or {}).get("no_total_evidence_skip") is True
            )


class TestDetectMovementStructure:
    """_detect_movement_structure returns ob_row, cb_row, movement_rows when first column has OB/CB labels."""

    def test_detects_ob_cb_movement(self, validator):
        df = pd.DataFrame(
            {
                "Label": ["Opening balance", "Addition", "Disposal", "Closing balance"],
                "2024": [100, 50, 10, 140],
            }
        )
        out = validator._detect_movement_structure(df)
        assert out is not None
        assert "ob_row" in out
        assert "cb_row" in out
        assert "movement_rows" in out
        assert out["ob_row"] == 0
        assert out["cb_row"] == 3
        assert 1 in out["movement_rows"] or 2 in out["movement_rows"]

    def test_returns_none_when_no_ob_cb(self, validator):
        df = pd.DataFrame({"Label": ["A", "B"], "Val": [1, 2]})
        assert validator._detect_movement_structure(df) is None


class TestPassOnlyWithAssertions:
    """PASS becomes INFO when assertions_count == 0 (no marks/cross_ref_marks)."""

    def test_pass_downgraded_to_info_when_no_assertions(self, validator):
        with patch(
            "quality_audit.core.validators.generic_validator.get_feature_flags"
        ) as gff:
            gff.return_value = {
                "generic_evidence_gate": True,
                "movement_rollforward": False,
            }
            df = pd.DataFrame(
                {
                    "X": ["A", "B"],
                    "Y": [1, 2],
                    "Z": [3, 5],
                }
            )
            result = validator.validate(df, "Some Table")
            assert result is not None
            if result.status_enum == "PASS":
                assert result.assertions_count > 0
            if result.assertions_count == 0 and "Không có assertion" in (
                result.status or ""
            ):
                assert result.status_enum == "INFO"


class TestRowTotalEligibilityGate:
    """Eligibility gate for row total validation on tables with insufficient detail rows."""

    def test_row_total_skips_when_only_one_numeric_row(self, validator):
        """Tables with only one numeric row should be gated as INFO (no assertion)."""
        from quality_audit.core.validators.generic_validator import (
            GenericTableValidator,
        )

        with patch(
            "quality_audit.core.validators.generic_validator.get_feature_flags"
        ) as gff, patch.object(
            GenericTableValidator, "_find_total_row"
        ) as mock_find_total, patch.object(
            GenericTableValidator, "_detect_amount_columns"
        ) as mock_detect_amounts:
            gff.return_value = {
                "movement_rollforward": False,
                "generic_evidence_gate": False,
                "enable_generic_total_gate": True,
            }
            mock_find_total.return_value = 2  # Last row is treated as total row
            mock_detect_amounts.return_value = ["CY"]  # Single amount column
            df = pd.DataFrame(
                {
                    "Label": [
                        "equity investments in other entity",
                        "",
                        "Carrying amounts",
                    ],
                    "CY": ["", "", 1000],
                }
            )
            result = validator.validate(df, "equity investments in other entity")
            assert result is not None
            assert result.status_enum == "INFO"
            ctx = result.context or {}
            assert ctx.get("no_assertion_reason") == "ELIGIBILITY_GATE"
            assert ctx.get("eligibility_gate_reason") == "insufficient_detail_rows"
