"""Tests for scoped_vertical_sum gating on empty detail rows (G3)."""

from unittest.mock import MagicMock

import pandas as pd
import pytest

from quality_audit.core.rules.scoped_vertical_sum import ScopedVerticalSumRule


@pytest.fixture
def rule():
    return ScopedVerticalSumRule()


@pytest.fixture
def materiality():
    m = MagicMock()
    m.compute.return_value = 1.0  # tolerance = 1.0
    return m


class TestScopedVerticalSumGating:
    """Tests for empty-details gating in scoped_vertical_sum."""

    def test_empty_details_nonzero_total_becomes_warn(self, rule, materiality):
        """Non-zero total with empty detail_rows list -> WARN, not FAIL.
        _parse_float never returns NaN, so valid_details is only empty
        when detail_rows itself is empty.
        """
        df = pd.DataFrame(
            {
                "Code": ["Total"],
                "Amount": ["1000"],
            }
        )
        evidence = rule.evaluate(
            df,
            materiality=materiality,
            table_type="GENERIC_NOTE",
            table_id="tbl_001",
            code_col="Code",
            amount_cols=["Amount"],
            total_row_idx=0,
            detail_rows=[],  # Explicitly empty
        )
        # Should have exactly one WARN evidence with NO_DETAIL_ROWS
        assert len(evidence) == 1
        ev = evidence[0]
        assert "NO_DETAIL_ROWS" in (
            ev.metadata.get("gate_reason_code", "") if ev.metadata else ""
        )
        # Must NOT be a fail
        assert ev.is_material is False or ev.is_material is None

    def test_empty_details_zero_total_skips_silently(self, rule, materiality):
        """Total=0, empty detail_rows list -> no evidence at all.
        Hits the original 'not valid_details and total_val == 0.0' continue.
        """
        df = pd.DataFrame(
            {
                "Code": ["Total"],
                "Amount": ["0"],
            }
        )
        evidence = rule.evaluate(
            df,
            materiality=materiality,
            table_type="GENERIC_NOTE",
            table_id="tbl_002",
            code_col="Code",
            amount_cols=["Amount"],
            total_row_idx=0,
            detail_rows=[],  # Explicitly empty
        )
        assert len(evidence) == 0

    def test_normal_mismatch_remains_fail(self, rule, materiality):
        """Valid details + mismatch -> FAIL (not gated)."""
        df = pd.DataFrame(
            {
                "Code": ["01", "02", "Total"],
                "Amount": ["100", "200", "999"],
            }
        )
        evidence = rule.evaluate(
            df,
            materiality=materiality,
            table_type="GENERIC_NOTE",
            table_id="tbl_003",
            code_col="Code",
            amount_cols=["Amount"],
            total_row_idx=2,
            detail_rows=[0, 1],
        )
        assert len(evidence) == 1
        ev = evidence[0]
        assert ev.is_material is True

    def test_details_present_pass(self, rule, materiality):
        """Valid details summing to total -> non-material PASS (not gated)."""
        df = pd.DataFrame(
            {
                "Code": ["01", "02", "Total"],
                "Amount": ["100", "200", "300"],
            }
        )
        evidence = rule.evaluate(
            df,
            materiality=materiality,
            table_type="GENERIC_NOTE",
            table_id="tbl_004",
            code_col="Code",
            amount_cols=["Amount"],
            total_row_idx=2,
            detail_rows=[0, 1],
        )
        assert len(evidence) == 1
        ev = evidence[0]
        assert ev.is_material is False
