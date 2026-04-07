import pandas as pd
import pytest

from quality_audit.config.feature_flags import get_feature_flags as _global_get_flags
from quality_audit.core.cache_manager import (
    AuditContext,
    LRUCacheManager,
    cross_check_cache,
)
from quality_audit.core.validators.cash_flow_validator import CashFlowValidator
from quality_audit.services.audit_service import AuditService


class TestCashFlowCrossTableRegistry:
    def _make_service(self) -> AuditService:
        ctx = AuditContext(cache=LRUCacheManager(max_size=100))
        return AuditService(context=ctx)

    def test_build_cf_registry_aggregates_across_tables(self):
        """
        _build_cf_registry should aggregate codes across multiple Cash Flow tables
        into a single document-level registry.
        """
        service = self._make_service()

        df1 = pd.DataFrame(
            {
                "Code": ["01", "02", "08"],
                "CY": [10.0, 20.0, 30.0],
                "PY": [5.0, 10.0, 15.0],
            }
        )
        df2 = pd.DataFrame(
            {
                "Code": ["03", "04", "08"],
                "CY": [5.0, 5.0, 10.0],
                "PY": [5.0, 5.0, 10.0],
            }
        )

        registry = service._build_cf_registry(
            [
                (df1, "Statement of Cash Flows", {}),
                (df2, "Statement of Cash Flows", {}),
            ]
        )

        # Individual codes preserved
        assert registry["01"] == (10.0, 5.0)
        assert registry["02"] == (20.0, 10.0)
        assert registry["03"] == (5.0, 5.0)
        assert registry["04"] == (5.0, 5.0)

        # Parent code 08 aggregated across tables
        assert registry["08"] == (40.0, 25.0)

    def test_validate_tables_marks_cross_table_used_for_cash_flow(
        self, monkeypatch: pytest.MonkeyPatch
    ):
        """
        When cashflow_cross_table_context is enabled and Cash Flow tables are present,
        _validate_tables should mark cross_table_used=True in the context for those tables.
        """

        def _flags_with_cf_enabled():
            flags = _global_get_flags().copy()
            flags["cashflow_cross_table_context"] = True
            flags["enable_big4_engine"] = False
            flags["baseline_authoritative_default"] = False
            return flags

        # Enable cross-table context in both AuditService and CashFlowValidator modules
        monkeypatch.setattr(
            "quality_audit.services.audit_service.get_feature_flags",
            lambda: _flags_with_cf_enabled(),
        )
        monkeypatch.setattr(
            "quality_audit.core.validators.cash_flow_validator.get_feature_flags",
            lambda: _flags_with_cf_enabled(),
        )

        service = self._make_service()

        # Simple Cash Flow-like table: numeric codes with CY/PY columns
        df = pd.DataFrame(
            {
                "Code": ["01", "02", "08"],
                "CY": [10.0, 20.0, 30.0],
                "PY": [5.0, 10.0, 15.0],
            }
        )

        # Heading ensures classifier routes to FS_CASH_FLOW
        heading = "Statement of Cash Flows"
        table_ctx = {"heading_source": "paragraph"}

        results = service._validate_tables([(df, heading, table_ctx)])

        assert len(results) == 1
        ctx = results[0]["context"]

        # Validator should be CashFlowValidator and cross-table flag should be set
        assert ctx.get("validator_type") == CashFlowValidator.__name__
        assert ctx.get("cross_table_used") is True

    def test_cashflow_missing_code_column_not_info_skipped(self):
        """Missing code column in cash flow should not return INFO_SKIPPED."""
        validator = CashFlowValidator()
        df = pd.DataFrame(
            {
                "Description": ["Operating cash flow", "Investing cash flow"],
                "CY": [10.0, 20.0],
                "PY": [8.0, 15.0],
            }
        )
        result = validator.validate(df, "Statement of Cash Flows", table_context={})
        assert result.rule_id in (
            "MISSING_CODE_COLUMN",
            "UNDETERMINED_HEADER_AFTER_CANONICALIZE",
        )
        assert result.status_enum == "WARN"

    def test_cashflow_effective_code_column_not_literal_code_header(self):
        """Code-like first column should be treated as effective code column."""
        validator = CashFlowValidator()
        df = pd.DataFrame(
            {
                "Unknown": ["20", "30", "40", "50", "60", "61", "70"],
                "Description": ["a", "b", "c", "d", "e", "f", "g"],
                "CY": [10.0, 20.0, 30.0, 60.0, 0.0, 0.0, 60.0],
                "PY": [10.0, 20.0, 30.0, 60.0, 0.0, 0.0, 60.0],
            }
        )
        result = validator.validate(df, "Statement of Cash Flows", table_context={})
        assert result.context.get("effective_code_column") == "Unknown"

    def test_cashflow_duplicate_codes_are_aggregated(self):
        """Repeated codes (e.g. repeated adjustments) must aggregate, not overwrite."""
        validator = CashFlowValidator()
        df = pd.DataFrame(
            {
                "Code": ["01", "02", "03", "04", "05", "05", "06", "07", "08"],
                "CY": [10.0, 20.0, 30.0, 40.0, 2.0, 3.0, 5.0, 6.0, 116.0],
                "PY": [10.0, 20.0, 30.0, 40.0, 2.0, 3.0, 5.0, 6.0, 116.0],
            }
        )
        result = validator.validate(df, "Statement of Cash Flows", table_context={})
        assert result.status.startswith("PASS:")

    def test_cashflow_code70_reconciles_with_cached_cash_equivalent(self):
        """When FS cash-equivalent evidence exists, code 70 should reconcile to it."""
        validator = CashFlowValidator()
        cross_check_cache.clear()
        cross_check_cache.set("cash and cash equivalents", (60.0, 60.0))
        df = pd.DataFrame(
            {
                "Code": ["20", "30", "40", "50", "60", "61", "70"],
                "CY": [10.0, 20.0, 30.0, 60.0, 0.0, 0.0, 60.0],
                "PY": [10.0, 20.0, 30.0, 60.0, 0.0, 0.0, 60.0],
            }
        )
        result = validator.validate(df, "Statement of Cash Flows", table_context={})
        # Other rule groups may fail on intentionally sparse fixtures;
        # verify 70 reconciliation itself does not add mismatch.
        assert "70 reconciliation with cash equivalents" not in result.status
