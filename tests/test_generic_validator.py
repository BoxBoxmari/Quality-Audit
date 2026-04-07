"""
Tests for GenericValidator fixed assets and cross-checking tables.
"""

import pandas as pd
import pytest

from quality_audit.config.feature_flags import FEATURE_FLAGS
from quality_audit.core.cache_manager import (
    AuditContext,
    cross_check_cache,
    cross_check_marks,
)
from quality_audit.core.validators.generic_validator import GenericTableValidator
from quality_audit.utils.column_detector import ColumnDetector


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

    def test_fixed_assets_parity_uses_last_column_for_cross_check(
        self, monkeypatch: pytest.MonkeyPatch
    ):
        """Fail-first parity lock: fixed assets cross-check must use legacy last column semantics."""
        df = pd.DataFrame(
            {
                "Item": [
                    "Cost",
                    "Machine 1",
                    "Total Cost",
                    "Accumulated depreciation",
                    "AD detail",
                    "Total AD",
                    "Net Book Value",
                    "Opening balance",
                    "Closing balance",
                ],
                "A": [0, 1, 1, 0, 1, 1, 0, 1, 1],
                "B": [0, 2, 2, 0, 2, 2, 0, 2, 2],
                "C": [0, 100, 100, 0, 100, 100, 0, 100, 100],
            }
        )

        monkeypatch.setitem(FEATURE_FLAGS, "legacy_parity_mode", True)

        def _wrong_detect(_df):
            return ("A", "A")

        monkeypatch.setattr(
            ColumnDetector,
            "detect_financial_columns_advanced",
            staticmethod(_wrong_detect),
        )

        observed: list[tuple[str, float, float]] = []

        def _capture_cross_check(
            self,
            _df,
            _cross_ref_marks,
            _issues,
            account_name,
            CY_bal,
            PY_bal,
            *_args,
            **_kwargs,
        ):
            observed.append((str(account_name), float(CY_bal), float(PY_bal)))

        monkeypatch.setattr(
            GenericTableValidator,
            "cross_check_with_BSPL",
            _capture_cross_check,
        )

        validator = GenericTableValidator(context=AuditContext())
        validator.validate(df, "tangible fixed assets")

        cost_rows = [row for row in observed if row[0] == "222"]
        assert cost_rows, "Expected cost cross-check call for account 222"
        assert cost_rows[0][1] == 100.0


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

    def test_form_2_net_revenue_prefers_detected_total_row_not_last_row(
        self, monkeypatch
    ):
        """Parity lock: FORM_2 net-revenue cross-check must use detected total row."""
        cross_check_cache.set("revenue from sales of goods", (400.0, 360.0))
        cross_check_cache.set("revenue deductions", (50.0, 45.0))
        cross_check_cache.set("net revenue (10 = 01 - 02)", (350.0, 315.0))

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
                    "Trailing note",
                ],
                "B": ["", 400, "", 400, "", 50, "", 50, 350, ""],
                "C": ["", 360, "", 360, "", 45, "", 45, 315, ""],
            }
        )

        ctx = AuditContext()
        validator = GenericTableValidator(context=ctx)
        monkeypatch.setattr(validator, "_find_total_row", lambda _df, **_: 8)

        # Isolate FORM_2 handler to lock net-revenue row selection semantics.
        calls = []

        def _capture_cross_check(
            _df,
            cross_ref_marks,
            _issues,
            account_name,
            CY_bal,
            PY_bal,
            CY_row,
            CY_col,
            gap_row,
            gap_col,
        ):
            calls.append(
                {
                    "account_name": account_name,
                    "CY_bal": CY_bal,
                    "PY_bal": PY_bal,
                    "CY_row": CY_row,
                    "CY_col": CY_col,
                    "gap_row": gap_row,
                    "gap_col": gap_col,
                }
            )
            cross_ref_marks.append({"account_name": account_name, "CY_row": CY_row})

        monkeypatch.setattr(validator, "cross_check_with_BSPL", _capture_cross_check)

        cross_ref_marks = []
        issues = []
        df_numeric = df.apply(pd.to_numeric, errors="coerce").fillna(0)
        validator._handle_cross_check_form_2(
            df=df,
            df_numeric=df_numeric,
            heading_lower="revenue from sales of goods and provision of services",
            end1=2,
            end2=6,
            cross_ref_marks=cross_ref_marks,
            issues=issues,
        )

        target_calls = [
            c for c in calls if c["account_name"] == "net revenue (10 = 01 - 02)"
        ]
        assert target_calls
        assert target_calls[0]["CY_row"] == 8
        assert target_calls[0]["CY_bal"] == 350
        assert target_calls[0]["PY_bal"] == 315

    def test_form_1_cross_check_prefers_detected_total_row_not_last_row(
        self, monkeypatch
    ):
        """Parity lock: FORM_1 cross-check must use detected total row when present."""
        df = pd.DataFrame(
            {
                "A": [
                    "Item 1",
                    "Item 2",
                    "Subtotal",
                    "Item 3",
                    "Grand Total",
                    "Trailing note",
                ],
                "B": [200, 300, 500, 500, 1000, ""],
                "C": [180, 270, 450, 450, 900, ""],
            }
        )

        ctx = AuditContext()
        validator = GenericTableValidator(context=ctx)
        monkeypatch.setattr(validator, "_find_total_row", lambda _df, **_: 4)

        result = validator.validate(df, "accounts receivable from customers")
        cy_marks = [
            m for m in result.cross_ref_marks if m.get("rule_id") == "CROSS_REF_BSPL_CY"
        ]
        py_marks = [
            m for m in result.cross_ref_marks if m.get("rule_id") == "CROSS_REF_BSPL_PY"
        ]

        assert cy_marks and py_marks
        assert all(m.get("ok") for m in cy_marks + py_marks)
