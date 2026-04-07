"""Tests for P0: BUILD_STAMP, P1: render-first signals_only, P5: float code normalization."""

import importlib

import pandas as pd
import pytest


class TestBuildStamp:
    """P0 — BUILD_STAMP must exist and be a non-empty string."""

    def test_build_stamp_exists(self):
        import quality_audit

        assert hasattr(quality_audit, "BUILD_STAMP")
        assert isinstance(quality_audit.BUILD_STAMP, str)
        assert len(quality_audit.BUILD_STAMP) > 0


class TestRenderFirstSignalsOnly:
    """P1 - render-first mode default is signals_only."""

    def test_default_mode_is_signals_only(self):
        from quality_audit.config.feature_flags import get_feature_flags

        flags = get_feature_flags()
        assert flags.get("extraction_render_first_triggered_mode") == "signals_only"


class TestFloatCodeNormalization:
    """P5 — float codes like 21.0 must be detected as code '21'."""

    def test_float_code_21_detected(self):
        from quality_audit.core.classification.structural_fingerprint import (
            StructuralFingerprinter,
        )

        fp_engine = StructuralFingerprinter()
        # Row with float code 21.0 and amounts
        data = {
            "Mã số": [21.0, 22.0, 30.0],
            "Item": ["Revenue from sales", "Deductions", "Net revenue"],
            "Current Year": [100_000, -20_000, 80_000],
            "Prior Year": [90_000, -15_000, 75_000],
        }
        df = pd.DataFrame(data)
        fp = fp_engine.extract(df)
        # After P5 normalization, "21", "22", "30" should be in found_codes
        assert (
            "21" in fp.found_codes
        ), f"Expected '21' in found_codes but got {fp.found_codes}"
        assert "22" in fp.found_codes
        assert "30" in fp.found_codes

    def test_float_nan_does_not_crash(self):
        from quality_audit.core.classification.structural_fingerprint import (
            StructuralFingerprinter,
        )

        fp_engine = StructuralFingerprinter()
        data = {
            "Code": [float("nan"), None, ""],
            "Item": ["A", "B", "C"],
            "Amount": [1000, 2000, 3000],
        }
        df = pd.DataFrame(data)
        # Should not raise
        fp = fp_engine.extract(df)
        assert "nan" not in fp.found_codes  # NaN must not become a code
