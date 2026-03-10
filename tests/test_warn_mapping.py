"""Tests for WARN status category mapping fix (G4)."""

from quality_audit.core.validators.base_validator import ValidationResult


class TestWarnMapping:
    """Verify WARN maps to STATUS_CATEGORY_WARN, not FAIL_DATA."""

    def test_warn_status_maps_to_warn_category(self):
        vr = ValidationResult(
            status="WARN: borderline extraction",
            status_enum="WARN",
        )
        d = vr.to_dict()
        assert d["status_category"] == "WARN", (
            f"Expected WARN category, got {d['status_category']}"
        )

    def test_fail_status_maps_to_fail_data_category(self):
        vr = ValidationResult(
            status="FAIL: mismatch",
            status_enum="FAIL",
        )
        d = vr.to_dict()
        assert d["status_category"] == "FAIL_DATA"

    def test_error_status_maps_to_fail_data_category(self):
        vr = ValidationResult(
            status="ERROR: runtime crash",
            status_enum="ERROR",
        )
        d = vr.to_dict()
        assert d["status_category"] == "FAIL_DATA"

    def test_pass_status_maps_to_pass_category(self):
        vr = ValidationResult(
            status="PASS: all checks OK",
            status_enum="PASS",
        )
        d = vr.to_dict()
        assert d["status_category"] == "PASS"

    def test_info_skipped_status_maps_to_info_skipped_category(self):
        vr = ValidationResult(
            status="INFO_SKIPPED: non-financial",
            status_enum="INFO_SKIPPED",
        )
        d = vr.to_dict()
        assert d["status_category"] == "INFO_SKIPPED"
