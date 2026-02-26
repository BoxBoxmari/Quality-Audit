"""
Tests for GenericValidator fixed assets and cross-checking tables.
"""

import pandas as pd

from quality_audit.core.cache_manager import (
    AuditContext,
    cross_check_cache,
    cross_check_marks,
)
from quality_audit.core.validators.generic_validator import GenericTableValidator


class TestFixedAssetsValidator:
    """Test fixed assets validation."""

    def setup_method(self):
        """Clear cache and marks before each test."""
        cross_check_cache.clear()
        cross_check_marks.clear()
        # Pre-populate cache with BSPL account values
        cross_check_cache.set("tangible fixed assets", (5000.0, 4500.0))
        cross_check_cache.set("222", (5000.0, 4500.0))
        cross_check_cache.set("223", (-1000.0, -900.0))

    def test_fixed_assets_cost_validation(self):
        """Test cost detail sum vs cost total validation."""
        df = pd.DataFrame(
            {
                "A": [
                    "Cost",
                    "Item 1",
                    "Item 2",
                    "Total Cost",
                    "AD",
                    "Item 1",
                    "Total AD",
                    "NBV",
                    "OB",
                    "CB",
                ],
                "B": ["", 2000, 3000, 5000, "", 500, 500, "", 4500, 4500],
                "C": ["", 1800, 2700, 4500, "", 450, 450, "", 4050, 4050],
            }
        )

        validator = GenericTableValidator()
        result = validator.validate(df, "tangible fixed assets")

        # Verify: Should have marks for cost validation
        cost_marks = [m for m in result.marks if "GV" in m.get("comment", "")]
        assert len(cost_marks) > 0

    def test_fixed_assets_cross_check_nbv(self):
        """Test cross-check for NBV with BSPL."""
        df = pd.DataFrame(
            {
                "A": [
                    "Cost",
                    "Item 1",
                    "Total Cost",
                    "AD",
                    "Item 1",
                    "Total AD",
                    "NBV",
                    "OB",
                    "CB",
                ],
                "B": ["", 2000, 2000, "", 500, 500, "", 1500, 1500],
                "C": ["", 1800, 1800, "", 450, 450, "", 1350, 1350],
            }
        )

        ctx = AuditContext()
        validator = GenericTableValidator(context=ctx)
        result = validator.validate(df, "tangible fixed assets")

        # Verify: Should have cross-ref marks for NBV (prefer context.marks)
        assert len(result.cross_ref_marks) > 0
        assert validator.context and "tangible fixed assets" in validator.context.marks

    def test_fixed_assets_cross_check_cost_account_222(self):
        """Test cross-check for cost with account 222."""
        df = pd.DataFrame(
            {
                "A": [
                    "Cost",
                    "Item 1",
                    "Total Cost",
                    "AD",
                    "Total AD",
                    "NBV",
                    "OB",
                    "CB",
                ],
                "B": ["", 2000, 2000, "", 500, "", 1500, 1500],
                "C": ["", 1800, 1800, "", 450, "", 1350, 1350],
            }
        )

        ctx = AuditContext()
        validator = GenericTableValidator(context=ctx)
        validator.validate(df, "tangible fixed assets")

        # Verify: Should have cross-ref marks for account 222 (prefer context.marks)
        assert validator.context and "222" in validator.context.marks

    def test_fixed_assets_cross_check_ad_account_223(self):
        """Test cross-check for accumulated depreciation with account 223."""
        df = pd.DataFrame(
            {
                "A": [
                    "Cost",
                    "Item 1",
                    "Total Cost",
                    "AD",
                    "Item 1",
                    "Total AD",
                    "NBV",
                    "OB",
                    "CB",
                ],
                "B": ["", 2000, 2000, "", 500, 500, "", 1500, 1500],
                "C": ["", 1800, 1800, "", 450, 450, "", 1350, 1350],
            }
        )

        ctx = AuditContext()
        validator = GenericTableValidator(context=ctx)
        validator.validate(df, "tangible fixed assets")

        # Verify: Should have cross-ref marks for account 223 (prefer context.marks)
        assert validator.context and "223" in validator.context.marks


class TestCrossCheckTables:
    """Test cross-checking for different table forms."""

    def setup_method(self):
        """Clear cache and marks before each test."""
        cross_check_cache.clear()
        cross_check_marks.clear()
        # Pre-populate cache
        cross_check_cache.set("accounts receivable from customers", (1000.0, 900.0))

    def test_form_1_cross_check_at_grand_total(self):
        """Test FORM_1 cross-check at grand total row."""
        df = pd.DataFrame(
            {
                "A": ["Item 1", "Item 2", "", "Subtotal", "Item 3", "Grand Total"],
                "B": [400, 300, "", 700, 300, 1000],
                "C": [360, 270, "", 630, 270, 900],
            }
        )

        ctx = AuditContext()
        validator = GenericTableValidator(context=ctx)
        result = validator.validate(df, "accounts receivable from customers")

        # Verify: Should have cross-ref marks (prefer context.marks)
        assert len(result.cross_ref_marks) > 0
        assert (
            validator.context
            and "accounts receivable from customers" in validator.context.marks
        )

    def test_form_2_cross_check_multiple_accounts(self):
        """Test FORM_2 cross-check at both subtotal and grand total."""
        cross_check_cache.set("revenue from sales of goods", (800.0, 720.0))
        cross_check_cache.set("revenue deductions", (100.0, 90.0))
        cross_check_cache.set("net revenue (10 = 01 - 02)", (700.0, 630.0))

        df = pd.DataFrame(
            {
                "A": [
                    "Revenue",
                    "Item 1",
                    "",
                    "Subtotal 1",
                    "Deductions",
                    "Item 1",
                    "",
                    "Subtotal 2",
                    "Grand Total",
                ],
                "B": ["", 400, "", 400, "", 50, "", 50, 350],
                "C": ["", 360, "", 360, "", 45, "", 45, 315],
            }
        )

        ctx = AuditContext()
        validator = GenericTableValidator(context=ctx)
        validator.validate(df, "revenue from sales of goods and provision of services")

        # Verify: Should have cross-ref marks for multiple accounts (prefer context.marks)
        assert (
            validator.context
            and "revenue from sales of goods" in validator.context.marks
        )
        assert "revenue deductions" in validator.context.marks
        assert "net revenue (10 = 01 - 02)" in validator.context.marks
