"""
Tests for BaseValidator cross-checking functionality.
"""

import pandas as pd

from quality_audit.core.cache_manager import (cross_check_cache,
                                              cross_check_marks)
from quality_audit.core.validators.generic_validator import \
    GenericTableValidator


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
