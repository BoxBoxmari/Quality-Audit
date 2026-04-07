"""
Tests for TaxValidator block-sum validation and cross-checking.
"""

from unittest.mock import patch

import pandas as pd

from quality_audit.core.cache_manager import cross_check_cache, cross_check_marks
from quality_audit.core.validators.tax_validator import TaxValidator


class TestTaxValidator:
    """Test tax validator functionality."""

    def setup_method(self):
        """Clear cache and marks before each test."""
        cross_check_cache.clear()
        cross_check_marks.clear()
        # Pre-populate cache with '50' for cross-checking
        cross_check_cache.set("50", (1000.0, 900.0))
        cross_check_cache.set("income tax", (200.0, 180.0))

    @patch("quality_audit.core.validators.tax_validator.get_validated_tax_rate")
    def test_tax_reconciliation_step_2_block_sum(self, mock_tax_rate):
        """Test Bước 2: Cumulative sum validation."""
        mock_tax_rate.return_value = 0.2

        df = pd.DataFrame(
            {
                "A": [
                    "Accounting profit before tax",
                    "Tax at rate",
                    "Item 1",
                    "Item 2",
                    "",
                    "Total 1",
                ],
                "B": [1000, 200, 50, 30, "", 280],
                "C": [900, 180, 45, 27, "", 252],
            }
        )

        validator = TaxValidator()
        result = validator.validate(df, "Reconciliation of effective tax rate")

        # Verify: Should have marks for Bước 2 validation
        step2_marks = [m for m in result.marks if "Bước 2" in m.get("comment", "")]
        assert len(step2_marks) > 0

    @patch("quality_audit.core.validators.tax_validator.get_validated_tax_rate")
    def test_tax_reconciliation_step_3_final_total(self, mock_tax_rate):
        """Test Bước 3: Final total validation."""
        mock_tax_rate.return_value = 0.2

        df = pd.DataFrame(
            {
                "A": [
                    "Accounting profit",
                    "Tax at rate",
                    "Item 1",
                    "Item 2",
                    "",
                    "Total 1",
                    "Item 3",
                    "Total 2",
                ],
                "B": [1000, 200, 50, 30, "", 280, 20, 300],
                "C": [900, 180, 45, 27, "", 252, 18, 270],
            }
        )

        validator = TaxValidator()
        result = validator.validate(df, "Reconciliation of effective tax rate")

        # Verify: Should have marks for Bước 3 validation
        step3_marks = [m for m in result.marks if "Bước 3" in m.get("comment", "")]
        assert len(step3_marks) > 0

    @patch("quality_audit.core.validators.tax_validator.get_validated_tax_rate")
    def test_tax_reconciliation_cross_check_account_50(self, mock_tax_rate):
        """Test cross-check for account code '50'."""
        mock_tax_rate.return_value = 0.2

        df = pd.DataFrame(
            {
                "A": ["Accounting profit before tax", "Tax at rate"],
                "B": [1000, 200],
                "C": [900, 180],
            }
        )

        validator = TaxValidator()
        result = validator.validate(df, "Reconciliation of effective tax rate")

        # Verify: Should have cross-ref marks for account '50'
        assert len(result.cross_ref_marks) > 0
        assert "50" in cross_check_marks

    @patch("quality_audit.core.validators.tax_validator.get_validated_tax_rate")
    def test_tax_reconciliation_cross_check_income_tax(self, mock_tax_rate):
        """Test cross-check for 'income tax' at last row."""
        mock_tax_rate.return_value = 0.2

        df = pd.DataFrame(
            {
                "A": ["Accounting profit", "Tax at rate", "Item 1", "", "Total"],
                "B": [1000, 200, 50, "", 250],
                "C": [900, 180, 45, "", 225],
            }
        )

        validator = TaxValidator()
        result = validator.validate(df, "Reconciliation of effective tax rate")

        # Verify: Should have cross-ref marks for 'income tax'
        [m for m in result.cross_ref_marks if "income tax" in str(m.get("comment", ""))]
        assert "income tax" in cross_check_marks

    @patch("quality_audit.core.validators.tax_validator.get_validated_tax_rate")
    @patch(
        "quality_audit.core.validators.tax_validator.ColumnDetector.detect_financial_columns_advanced"
    )
    def test_tax_reconciliation_uses_detected_financial_columns(
        self, mock_detect_columns, mock_tax_rate
    ):
        """Parity lock: use detected current/prior year columns instead of hardcoded last-2 columns."""
        mock_tax_rate.return_value = 0.2
        mock_detect_columns.return_value = ("FY2024", "FY2023")

        df = pd.DataFrame(
            {
                "A": ["Accounting profit before tax", "Tax at rate", "", "Total"],
                "FY2024": [1000, 200, "", 200],
                "FY2023": [900, 180, "", 180],
                "Notes": ["memo", "memo", "", "memo"],
            }
        )

        validator = TaxValidator()
        result = validator.validate(df, "Reconciliation of effective tax rate")
        cy_marks = [
            m for m in result.cross_ref_marks if m.get("rule_id") == "CROSS_REF_BSPL_CY"
        ]
        py_marks = [
            m for m in result.cross_ref_marks if m.get("rule_id") == "CROSS_REF_BSPL_PY"
        ]

        assert cy_marks and py_marks
        assert all(m.get("ok") for m in cy_marks + py_marks)
