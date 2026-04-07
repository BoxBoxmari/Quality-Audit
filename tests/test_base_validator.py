"""
Tests for BaseValidator cross-checking functionality.
"""

from unittest.mock import patch

import pandas as pd

from quality_audit.core.cache_manager import cross_check_cache, cross_check_marks
from quality_audit.core.parity.legacy_baseline import KEY_AR_LONG, KEY_AR_LONG_ASCII
from quality_audit.core.validators.base_validator import ValidationResult
from quality_audit.core.validators.generic_validator import GenericTableValidator


class TestCrossCheckWithBSPL:
    """Test cross_check_with_BSPL method."""

    def setup_method(self):
        """Clear cache and marks before each test."""
        cross_check_cache.clear()
        cross_check_marks.clear()

    def test_cross_check_with_matching_values(self):
        """Test cross-check when values match."""
        # Setup: Store value in cache
        cross_check_cache.set("test_account", (1000.0, 900.0))

        # Create test DataFrame
        df = pd.DataFrame(
            {"A": ["Value", 1000, 900], "B": ["CY", 1000, 900], "C": ["PY", 900, 800]}
        )

        validator = GenericTableValidator()
        cross_ref_marks = []
        issues = []

        # Perform cross-check
        validator.cross_check_with_BSPL(
            df, cross_ref_marks, issues, "test_account", 1000.0, 900.0, 1, 1, 0, -1
        )

        # Verify: Should have 2 marks (CY and PY), both ok=True
        assert len(cross_ref_marks) == 2
        assert all(mark["ok"] for mark in cross_ref_marks)
        assert len(issues) == 0

    def test_cross_check_with_mismatched_values(self):
        """Test cross-check when values don't match."""
        # Setup: Store value in cache
        cross_check_cache.set("test_account", (1000.0, 900.0))

        # Create test DataFrame
        df = pd.DataFrame(
            {"A": ["Value", 1000, 900], "B": ["CY", 1000, 900], "C": ["PY", 900, 800]}
        )

        validator = GenericTableValidator()
        cross_ref_marks = []
        issues = []

        # Perform cross-check with mismatched values
        validator.cross_check_with_BSPL(
            df, cross_ref_marks, issues, "test_account", 1100.0, 950.0, 1, 1, 0, -1
        )

        # Verify: Should have 2 marks, both ok=False, and 2 issues
        assert len(cross_ref_marks) == 2
        assert all(not mark["ok"] for mark in cross_ref_marks)
        assert len(issues) == 2
        assert "Sai lệch = 100" in issues[0]
        assert "Sai lệch = 50" in issues[1]

    def test_cross_check_without_cache_entry(self):
        """Test cross-check when account not in cache."""
        # Don't set anything in cache

        df = pd.DataFrame(
            {"A": ["Value", 1000, 900], "B": ["CY", 1000, 900], "C": ["PY", 900, 800]}
        )

        validator = GenericTableValidator()
        cross_ref_marks = []
        issues = []

        # Perform cross-check
        validator.cross_check_with_BSPL(
            df, cross_ref_marks, issues, "test_account", 1000.0, 900.0, 1, 1, 0, -1
        )

        # Verify: Should have no marks or issues (early return)
        assert len(cross_ref_marks) == 0
        assert len(issues) == 0

    def test_cross_check_parity_alias_bridge_ar_long_ascii(self):
        """Parity: allow AR long-term key lookup via ASCII alias fallback."""
        cross_check_cache.set(KEY_AR_LONG_ASCII, (1200.0, 1100.0))

        df = pd.DataFrame(
            {
                "A": ["Value", 1200, 1100],
                "B": ["CY", 1200, 1100],
                "C": ["PY", 1100, 1000],
            }
        )
        validator = GenericTableValidator()
        cross_ref_marks = []
        issues = []

        # Request canonical en-dash key while cache stores ASCII hyphen key.
        validator.cross_check_with_BSPL(
            df, cross_ref_marks, issues, KEY_AR_LONG, 1200.0, 1100.0, 1, 1, 0, -1
        )

        assert len(cross_ref_marks) == 2
        assert all(mark["ok"] for mark in cross_ref_marks)
        assert len(issues) == 0

    def test_ticket9_guards_disabled_in_parity_mode(self):
        """Parity mode: Ticket-9 magnitude/section guards must not block cross-check."""
        cross_check_cache.set("chi phí trả trước ngắn hạn", (1_000_000.0, 900_000.0))

        df = pd.DataFrame(
            {"A": ["Value", 1000, 900], "B": ["CY", 1000, 900], "C": ["PY", 900, 800]}
        )
        # Intentionally mismatched heading token to trigger section guard in non-parity mode.
        df.attrs["heading"] = "Chi phí trả trước dài hạn"

        validator = GenericTableValidator()
        cross_ref_marks = []
        issues = []

        with patch(
            "quality_audit.core.validators.base_validator.get_feature_flags",
            return_value={"legacy_parity_mode": True},
        ):
            validator.cross_check_with_BSPL(
                df,
                cross_ref_marks,
                issues,
                "chi phí trả trước ngắn hạn",
                1000.0,
                900.0,
                1,
                1,
                0,
                -1,
            )

        # Without Ticket-9 guard in parity mode, cross-check executes normally.
        assert len(cross_ref_marks) == 2
        assert len(issues) == 2

    def test_ticket9_guards_active_when_non_parity_mode(self):
        """Non-parity mode: Ticket-9 magnitude/section guards can block suspicious cross-check."""
        cross_check_cache.set("chi phí trả trước ngắn hạn", (1_000_000.0, 900_000.0))

        df = pd.DataFrame(
            {"A": ["Value", 1000, 900], "B": ["CY", 1000, 900], "C": ["PY", 900, 800]}
        )
        df.attrs["heading"] = "Chi phí trả trước dài hạn"

        validator = GenericTableValidator()
        cross_ref_marks = []
        issues = []

        with patch(
            "quality_audit.core.validators.base_validator.get_feature_flags",
            return_value={"legacy_parity_mode": False},
        ):
            validator.cross_check_with_BSPL(
                df,
                cross_ref_marks,
                issues,
                "chi phí trả trước ngắn hạn",
                1000.0,
                900.0,
                1,
                1,
                0,
                -1,
            )

        # Guard blocks this suspicious mapping in non-parity mode.
        assert len(cross_ref_marks) == 0
        assert len(issues) == 0

    def test_cross_check_position_adjustment(self):
        """Test position adjustment for special account types."""
        # Setup
        cross_check_cache.set("revenue", (1000.0, 900.0))

        df = pd.DataFrame(
            {"A": ["Value", 1000, 900], "B": ["CY", 1000, 900], "C": ["PY", 900, 800]}
        )

        validator = GenericTableValidator()
        cross_ref_marks = []
        issues = []

        # Perform cross-check with "revenue" in account_name (triggers adjustment)
        validator.cross_check_with_BSPL(
            df, cross_ref_marks, issues, "revenue", 1000.0, 900.0, 1, 1, 0, -1
        )

        # Verify: Marks should use adjusted positions
        assert len(cross_ref_marks) == 2
        # Adjusted row should be CY_row - 1, adjusted col should be len(df.columns)
        assert cross_ref_marks[0]["row"] == 0  # 1 - 1
        assert cross_ref_marks[0]["col"] == 3  # len(df.columns) = 3

    def test_cross_check_uses_context_cache_instead_of_global_cache(self):
        """Regression: context cache must isolate runs from leaked global cache state."""
        # Simulate leaked global state from a previous run.
        cross_check_cache.set("test_account", (9999.0, 9999.0))

        df = pd.DataFrame(
            {
                "A": ["Value", 2000, 1800],
                "B": ["CY", 2000, 1800],
                "C": ["PY", 1800, 1600],
            }
        )

        from quality_audit.core.cache_manager import AuditContext

        context = AuditContext()
        context.cache.set("test_account", (2000.0, 1800.0))

        validator = GenericTableValidator(context=context)
        cross_ref_marks = []
        issues = []

        validator.cross_check_with_BSPL(
            df, cross_ref_marks, issues, "test_account", 2000.0, 1800.0, 1, 1, 0, -1
        )

        # If context-local cache is respected, both checks pass and no mismatch issue is raised.
        assert len(cross_ref_marks) == 2
        assert all(mark["ok"] for mark in cross_ref_marks)
        assert len(issues) == 0

    def test_cross_check_uses_context_marks_instead_of_global_marks(self):
        """Regression: context marks must be updated without leaking into global marks."""
        from quality_audit.core.cache_manager import AuditContext

        context = AuditContext()
        context.cache.set("test_account", (1000.0, 900.0))
        cross_check_marks.clear()

        df = pd.DataFrame(
            {"A": ["Value", 1000, 900], "B": ["CY", 1000, 900], "C": ["PY", 900, 800]}
        )
        validator = GenericTableValidator(context=context)
        cross_ref_marks = []
        issues = []

        validator.cross_check_with_BSPL(
            df, cross_ref_marks, issues, "test_account", 1000.0, 900.0, 1, 1, 0, -1
        )

        assert "test_account" in context.marks
        assert "test_account" not in cross_check_marks


class TestPassGating:
    """Test _enforce_pass_gating and treat_no_assertion_as_pass flag."""

    def test_treat_no_assertion_as_pass_true_keeps_pass(self):
        """When treat_no_assertion_as_pass=True and assertions_count=0, PASS is kept."""
        result = ValidationResult(
            status="PASS",
            status_enum="PASS",
            marks=[],
        )
        validator = GenericTableValidator()
        with patch(
            "quality_audit.core.validators.base_validator.get_feature_flags",
            return_value={
                "legacy_parity_mode": False,
                "treat_no_assertion_as_pass": True,
            },
        ):
            out = validator._enforce_pass_gating(result, 0, 0.5)
        assert out.status_enum == "PASS"
        assert out.status == "PASS"

    def test_treat_no_assertion_as_pass_false_overrides_to_info_skipped(self):
        """When treat_no_assertion_as_pass=False and assertions_count=0, PASS becomes INFO_SKIPPED."""
        result = ValidationResult(
            status="PASS",
            status_enum="PASS",
            marks=[],
        )
        validator = GenericTableValidator()
        with patch(
            "quality_audit.core.validators.base_validator.get_feature_flags",
            return_value={
                "legacy_parity_mode": False,
                "treat_no_assertion_as_pass": False,
            },
        ):
            out = validator._enforce_pass_gating(result, 0, 0.5)
        assert out.status_enum == "INFO_SKIPPED"
        assert "No assertions" in (out.status or "")
        assert out.context.get("failure_reason_code") == "NO_ASSERTIONS"

    def test_parity_mode_overrides_treat_no_assertion_policy(self):
        """In parity mode, assertions_count=0 must not remain PASS even if policy is True."""
        result = ValidationResult(
            status="PASS",
            status_enum="PASS",
            marks=[],
        )
        validator = GenericTableValidator()
        with patch(
            "quality_audit.core.validators.base_validator.get_feature_flags",
            return_value={
                "legacy_parity_mode": True,
                "treat_no_assertion_as_pass": True,
            },
        ):
            out = validator._enforce_pass_gating(result, 0, 0.5)
        assert out.status_enum == "INFO_SKIPPED"
        assert out.context.get("failure_reason_code") == "NO_ASSERTIONS"

    def test_warn_capping_borderline_confidence_sets_warn(self):
        result = ValidationResult(status="PASS", status_enum="PASS", marks=[])
        validator = GenericTableValidator()
        out = validator._apply_warn_capping(
            result, {"quality_flags": ["BORDERLINE_CONFIDENCE"]}
        )
        assert out.status_enum == "WARN"
        assert out.status.startswith("WARN (capped):")
        assert out.context.get("BORDERLINE_EXTRACTION_CONFIDENCE") is True
        assert out.context.get("original_status_enum") == "PASS"

    def test_warn_capping_quality_score_range_sets_warn(self):
        result = ValidationResult(status="PASS", status_enum="PASS", marks=[])
        validator = GenericTableValidator()
        out = validator._apply_warn_capping(result, {"quality_score": 0.7})
        assert out.status_enum == "WARN"
        assert out.status.startswith("WARN (capped):")
        assert out.context.get("BORDERLINE_EXTRACTION_CONFIDENCE") is True
        assert out.context.get("original_status_enum") == "PASS"

    def test_warn_capping_not_applied_for_high_confidence(self):
        result = ValidationResult(status="PASS", status_enum="PASS", marks=[])
        validator = GenericTableValidator()
        out = validator._apply_warn_capping(result, {"quality_score": 0.9})
        assert out.status_enum == "PASS"
        assert out.context.get("BORDERLINE_EXTRACTION_CONFIDENCE") is None
