"""
Tests for text formula tolerance (Ticket 2).
Verifies that percentage and additive formulas use compare_amounts
instead of strict integer rounding.
"""

import pandas as pd

from quality_audit.core.validators.generic_validator import GenericTableValidator


class TestTextFormulaTolerance:
    """Ticket 2: Replace strict abs(round(diff)) == 0 with compare_amounts."""

    def test_percentage_formula_passes_within_tolerance(self):
        """A rounding difference of 0.01 should PASS, not FAIL."""
        # Row 0: base value; Row 1: "x 20%" formula row
        df = pd.DataFrame(
            {
                "Label": ["Revenue", "x 20% tax"],
                "Code": ["10", "11"],
                "Amount": [1234567.89, 246913.58],  # exact = 246913.578 → diff = 0.002
            }
        )
        validator = GenericTableValidator()
        result = validator._evaluate_text_formula(
            df,
            df[["Label", "Code", "Amount"]]
            .astype(object)
            .map(lambda x: pd.to_numeric(str(x).replace(",", ""), errors="coerce")),
            {"Code"},
        )
        # Should produce a result with assertions and no issues
        assert result is not None
        assert result.status_enum == "PASS"
        fail_marks = [m for m in result.marks if not m.get("ok")]
        assert len(fail_marks) == 0

    def test_additive_formula_passes_with_rounding(self):
        """30 = 20 + 21 with rounding diff < tolerance should PASS."""
        df = pd.DataFrame(
            {
                "Label": [
                    "Item A (20)",
                    "Item B (21)",
                    "Total (30 = 20 + 21)",
                ],
                "Code": ["20", "21", "30"],
                "Amount": [500000.005, 300000.003, 800000.01],
                # exact sum = 800000.008, diff = 0.002
            }
        )
        validator = GenericTableValidator()
        result = validator._evaluate_text_formula(
            df,
            df[["Label", "Code", "Amount"]]
            .astype(object)
            .map(lambda x: pd.to_numeric(str(x).replace(",", ""), errors="coerce")),
            {"Code"},
        )
        assert result is not None
        assert result.status_enum == "PASS"
        fail_marks = [m for m in result.marks if not m.get("ok")]
        assert len(fail_marks) == 0

    def test_large_diff_still_fails(self):
        """A genuine mismatch (diff > tolerance) should still FAIL."""
        df = pd.DataFrame(
            {
                "Label": ["Revenue", "x 20% tax"],
                "Code": ["10", "11"],
                "Amount": [1000000, 250000],  # expected = 200000, diff = 50000
            }
        )
        validator = GenericTableValidator()
        result = validator._evaluate_text_formula(
            df,
            df[["Label", "Code", "Amount"]]
            .astype(object)
            .map(lambda x: pd.to_numeric(str(x).replace(",", ""), errors="coerce")),
            {"Code"},
        )
        assert result is not None
        assert result.status_enum == "FAIL"
        fail_marks = [m for m in result.marks if not m.get("ok")]
        assert len(fail_marks) > 0
