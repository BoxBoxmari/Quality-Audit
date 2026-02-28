"""
Tests for Phase 3 rule classes:
  - SumWithinToleranceRule
  - MovementEquationRule
  - CrossCheckRule
"""

import pandas as pd
import pytest

from quality_audit.core.evidence.severity import Severity
from quality_audit.core.materiality import MaterialityEngine
from quality_audit.core.rules import (
    CrossCheckRule,
    MovementEquationRule,
    SumWithinToleranceRule,
)


@pytest.fixture
def materiality_engine():
    """Provides a default MaterialityEngine for testing."""
    return MaterialityEngine()


def _make_table(rows):
    return pd.DataFrame(rows)


# ---------------------------------------------------------------------------
# SumWithinToleranceRule
# ---------------------------------------------------------------------------


class TestSumWithinToleranceRule:
    def test_sum_exact_match(self, materiality_engine):
        df = _make_table(
            [
                {"ColA": 100},
                {"ColA": 200},
                {"ColA": 300},  # Total row
            ]
        )
        rule = SumWithinToleranceRule()
        evidence = rule.evaluate(
            df=df,
            materiality=materiality_engine,
            table_type="FS_BALANCE_SHEET",
            amount_cols=["ColA"],
            total_row_idx=2,
            detail_rows=[0, 1],
        )
        assert len(evidence) == 1
        ev = evidence[0]
        assert ev.is_material is False
        assert ev.severity == Severity.INFO
        assert ev.expected == 300
        assert ev.actual == 300

    def test_sum_within_tolerance(self, materiality_engine):
        df = _make_table(
            [
                {"ColA": 100.2},
                {"ColA": 200.3},
                {"ColA": 300.0},  # Total row, diff is 0.5
            ]
        )
        rule = SumWithinToleranceRule()
        evidence = rule.evaluate(
            df=df,
            materiality=materiality_engine,
            table_type="FS_BALANCE_SHEET",
            amount_cols=["ColA"],
            total_row_idx=2,
            detail_rows=[0, 1],
        )
        assert len(evidence) == 1
        ev = evidence[0]
        # Diff is 0.5. Tolerance for 300 should be ~1.0.
        assert ev.is_material is False
        assert ev.severity == Severity.INFO

    def test_sum_material_diff(self, materiality_engine):
        df = _make_table(
            [
                {"ColA": 100},
                {"ColA": 500},
                {"ColA": 300},  # Total row, diff is 300. Huge!
            ]
        )
        rule = SumWithinToleranceRule()
        evidence = rule.evaluate(
            df=df,
            materiality=materiality_engine,
            table_type="FS_BALANCE_SHEET",
            amount_cols=["ColA"],
            total_row_idx=2,
            detail_rows=[0, 1],
        )
        assert len(evidence) == 1
        ev = evidence[0]
        assert ev.is_material is True
        assert ev.severity == Severity.MAJOR
        assert ev.diff == 300

    def test_sum_default_details(self, materiality_engine):
        # If detail_rows is Note, sums 0..total_row_idx-1
        df = _make_table(
            [
                {"ColA": 50},
                {"ColA": 50},
                {"ColA": 100},  # Total row
            ]
        )
        rule = SumWithinToleranceRule()
        evidence = rule.evaluate(
            df=df,
            materiality=materiality_engine,
            table_type="FS_INCOME_STATEMENT",
            amount_cols=["ColA"],
            total_row_idx=2,
        )
        assert len(evidence) == 1
        assert evidence[0].is_material is False

    def test_sum_skip_invalid_cols(self, materiality_engine):
        df = _make_table(
            [
                {"ColA": 100, "ColB": "abc"},
                {"ColA": 200, "ColB": "def"},
                {"ColA": 300, "ColB": "total"},
            ]
        )
        rule = SumWithinToleranceRule()
        evidence = rule.evaluate(
            df=df,
            materiality=materiality_engine,
            table_type="GENERIC_NOTE",
            amount_cols=["ColA", "ColB"],
            total_row_idx=2,
        )
        # Should only return evidence for ColA
        assert len(evidence) == 1
        assert evidence[0].source_cols == ["ColA"]


# ---------------------------------------------------------------------------
# MovementEquationRule
# ---------------------------------------------------------------------------


class TestMovementEquationRule:
    def test_movement_exact_match(self, materiality_engine):
        df = _make_table(
            [
                {"ColA": 1000},  # OB
                {"ColA": 200},  # Move 1
                {"ColA": -50},  # Move 2
                {"ColA": 1150},  # CB
            ]
        )
        rule = MovementEquationRule()
        evidence = rule.evaluate(
            df=df,
            materiality=materiality_engine,
            table_type="GENERIC_NOTE",
            amount_cols=["ColA"],
            ob_row_idx=0,
            cb_row_idx=3,
            movement_rows=[1, 2],
        )
        assert len(evidence) == 1
        ev = evidence[0]
        assert ev.is_material is False
        assert ev.expected == 1150
        assert ev.actual == 1150

    def test_movement_material_diff(self, materiality_engine):
        df = _make_table(
            [
                {"ColA": 1000},  # OB
                {"ColA": 500},  # Move 1
                {"ColA": 1200},  # CB => diff is 300
            ]
        )
        rule = MovementEquationRule()
        evidence = rule.evaluate(
            df=df,
            materiality=materiality_engine,
            table_type="GENERIC_NOTE",
            amount_cols=["ColA"],
            ob_row_idx=0,
            cb_row_idx=2,
            movement_rows=[1],
        )
        assert len(evidence) == 1
        ev = evidence[0]
        assert ev.is_material is True
        assert ev.severity == Severity.MAJOR
        assert ev.expected == 1500
        assert ev.actual == 1200


# ---------------------------------------------------------------------------
# CrossCheckRule
# ---------------------------------------------------------------------------


class TestCrossCheckRule:
    def test_cross_check_exact_match(self, materiality_engine):
        df = _make_table(
            [
                {"Col1": 500},
                {"Col1": 1500},  # Target cell
            ]
        )
        rule = CrossCheckRule()
        evidence = rule.evaluate(
            df=df,
            materiality=materiality_engine,
            table_type="FS_CASH_FLOW",
            verify_items=[
                {
                    "row_idx": 1,
                    "col_name": "Col1",
                    "expected_value": 1500.0,
                    "reference_name": "BS_Cash",
                }
            ],
        )
        assert len(evidence) == 1
        ev = evidence[0]
        assert ev.is_material is False
        assert ev.severity == Severity.INFO
        assert ev.metadata["reference_name"] == "BS_Cash"

    def test_cross_check_material_diff(self, materiality_engine):
        df = _make_table(
            [
                {"Col1": 1500},  # Target cell
            ]
        )
        rule = CrossCheckRule()
        evidence = rule.evaluate(
            df=df,
            materiality=materiality_engine,
            table_type="GENERIC_NOTE",
            verify_items=[
                {
                    "row_idx": 0,
                    "col_name": "Col1",
                    "expected_value": 2000.0,
                    "reference_name": "IS_Revenue",
                }
            ],
        )
        assert len(evidence) == 1
        ev = evidence[0]
        assert ev.is_material is True
        assert ev.severity == Severity.MAJOR
        assert ev.expected == 2000.0
        assert ev.actual == 1500.0
