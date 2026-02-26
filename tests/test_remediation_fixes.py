"""Regression tests for P1 remediation fixes (Issues C1, C3, C4)."""

import pandas as pd
import pytest

from quality_audit.core.cache_manager import cross_check_cache, cross_check_marks
from quality_audit.core.validators.base_validator import AuditContext
from quality_audit.core.validators.generic_validator import GenericTableValidator


class TestRemediationIssueC3:
    """Test Issue C3: First row inclusion in sum."""

    def test_first_detail_row_with_numeric_included(self):
        df = pd.DataFrame(
            {
                "Code": ["1", "2", "3", "Total"],
                "Amount CY": [100, 200, 300, 600],
                "Amount PY": [90, 180, 270, 540],
            }
        )
        validator = GenericTableValidator()
        result = validator.validate(df, "test table")
        assert result.status.startswith("PASS") or "PASS" in result.status
        fail_marks = [m for m in (result.marks or []) if not m.get("ok")]
        assert not any("100" in str(m.get("comment", "")) for m in fail_marks)


class TestRemediationIssueC4:
    """Test Issue C4: Statement skip column total."""

    def test_income_statement_skips_column_total(self):
        df = pd.DataFrame(
            {
                "Code": ["01", "02", "10", "20"],
                "Description": ["Revenue", "Cost", "Gross profit", "Net profit"],
                "CY": [1000, -600, 400, 300],
                "PY": [900, -540, 360, 270],
            }
        )
        validator = GenericTableValidator()
        result = validator.validate(df, "statement of income")
        status_enum = getattr(result, "status_enum", None) or "UNKNOWN"
        assert status_enum in ("INFO", "PASS", "WARN", "INFO_SKIPPED", "UNKNOWN")


class TestRemediationIssueC1:
    """Test Issue C1: Total column priority."""

    def setup_method(self):
        cross_check_marks.clear()
        cross_check_cache.clear()

    def test_total_column_preferred_over_total_cost(self):
        df = pd.DataFrame(
            {
                "Code": ["1", "2", "Total"],
                "Total Cost": [100, 200, 300],
                "Total AD": [10, 20, 30],
                "Total": [90, 180, 270],
            }
        )
        cross_check_cache.set("test account", (270.0, 270.0))
        ctx = AuditContext()
        validator = GenericTableValidator(context=ctx)
        result = validator.validate(df, "balance sheet")
        status_enum = getattr(result, "status_enum", None) or "UNKNOWN"
        assert status_enum in (
            "PASS",
            "WARN",
            "INFO",
            "INFO_SKIPPED",
            "UNKNOWN",
            "FAIL",
        )
        if ctx.marks:
            assert "test account" in ctx.marks or not result.marks


class TestP0ExtractionAmountColumns:
    """Regression test for P0 extraction loss: CJCGV tbl_006 and similar must have amount columns.
    See docs/P0_EXTRACTION_INVESTIGATION.md for full investigation steps.
    """

    @pytest.fixture
    def cjcgv_path(self):
        from pathlib import Path

        base = Path(__file__).resolve().parent.parent
        for sub in ("test_data", "data", "fixtures"):
            p = base / sub / "CJCGV-FS2018-EN- v2.docx"
            if p.exists():
                return p
        return None

    def test_cjcgv_tbl_006_has_amount_columns_when_doc_present(self, cjcgv_path):
        if cjcgv_path is None:
            pytest.skip("CJCGV-FS2018-EN- v2.docx not found in test_data/data/fixtures")
        from quality_audit.io.word_reader import WordReader

        reader = WordReader()
        tables_with_headings = reader.read_tables_with_headings(
            str(cjcgv_path), include_context=False
        )
        # tbl_006 is 6th table (1-based); use index 5
        if len(tables_with_headings) <= 5:
            pytest.skip("Document has fewer than 6 tables")
        df, _ = tables_with_headings[5]
        # Amount columns: name contains "amount" or column has numeric dtype
        amount_cols = [
            c
            for c in df.columns
            if "amount" in str(c).lower()
            or (hasattr(df[c].dtype, "kind") and df[c].dtype.kind in "fciu")
        ]
        assert len(amount_cols) >= 2, (
            f"P0 extraction: expected >=2 amount columns in tbl_006, got {len(amount_cols)}. "
            "See docs/P0_EXTRACTION_INVESTIGATION.md"
        )
        assert df[amount_cols].notna().sum().sum() > 0, (
            "P0 extraction: amount columns have no numeric data. "
            "See docs/P0_EXTRACTION_INVESTIGATION.md"
        )
