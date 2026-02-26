"""
SCRUM-6 Regression Tests: IndexError prevention for 5 failing tables.

Tests ensure that tables with edge case dimensions no longer crash with IndexError,
but instead degrade gracefully (skip validation or return WARN status).
"""

import pandas as pd

from quality_audit.core.cache_manager import cross_check_cache, cross_check_marks
from quality_audit.core.validators.generic_validator import GenericTableValidator


class TestSCRUM6RegressionIndexError:
    """
    Regression tests for SCRUM-6: Prevent IndexError on 5 specific tables.

    These tables previously crashed due to out-of-bounds access when
    end1 + 1 >= len(df) in various cross-check handlers.
    """

    def setup_method(self):
        """Clear cache and marks before each test."""
        cross_check_cache.clear()
        cross_check_marks.clear()

    def test_equity_investments_small_table_no_crash(self):
        """
        Test: Equity investments in other entity with 6 rows.

        Previously crashed with: IndexError: index 6 is out of bounds for axis 0 with size 6

        Expected: No exception, validation completes (may return INFO/WARN status).
        """
        # Create minimal table matching the crash pattern
        df = pd.DataFrame(
            {
                "A": ["Item 1", "Item 2", "Item 3", "Item 4", "Item 5", "Total"],
                "B": [100, 200, 300, 400, 500, 1500],
                "C": [90, 180, 270, 360, 450, 1350],
            }
        )

        validator = GenericTableValidator()

        # Should not raise any exception
        result = validator.validate(df, "equity investments in other entity")

        # Verify no exception occurred (test passes if we get here)
        assert result is not None
        assert hasattr(result, "status")
        # Status should not contain "ERROR" related to IndexError
        assert "IndexError" not in result.status

    def test_other_current_assets_4_rows_no_crash(self):
        """
        Test: Other current assets with 4 rows.

        Previously crashed with: IndexError: index 4 is out of bounds for axis 0 with size 4

        Expected: No exception, validation completes.
        """
        df = pd.DataFrame(
            {
                "A": ["Description 1", "Description 2", "Description 3", "Total"],
                "B": [1000, 2000, 3000, 6000],
                "C": [900, 1800, 2700, 5400],
            }
        )

        validator = GenericTableValidator()

        # Should not raise any exception
        result = validator.validate(df, "other current assets")

        assert result is not None
        assert "IndexError" not in result.status

    def test_other_long_term_assets_4_rows_no_crash(self):
        """
        Test: Other long-term assets with 4 rows.

        Previously crashed with: IndexError: index 4 is out of bounds for axis 0 with size 4

        Expected: No exception, validation completes.
        """
        df = pd.DataFrame(
            {
                "A": ["Asset 1", "Asset 2", "Asset 3", "Total"],
                "B": [500, 1500, 2000, 4000],
                "C": [450, 1350, 1800, 3600],
            }
        )

        validator = GenericTableValidator()

        # Should not raise any exception
        result = validator.validate(df, "other long-term assets")

        assert result is not None
        assert "IndexError" not in result.status

    def test_accounts_payable_related_companies_13_rows_no_crash(self):
        """
        Test: Accounts payable to related companies with 13 rows.

        Previously crashed with: IndexError: index 13 is out of bounds for axis 0 with size 13

        Expected: No exception, validation completes.
        """
        data = {
            "A": [f"Company {i}" for i in range(1, 13)] + ["Total"],
            "B": [100 * i for i in range(1, 13)] + [7800],
            "C": [90 * i for i in range(1, 13)] + [7020],
        }
        df = pd.DataFrame(data)

        validator = GenericTableValidator()

        # Should not raise any exception
        result = validator.validate(df, "accounts payable to related companies")

        assert result is not None
        assert "IndexError" not in result.status

    def test_production_business_costs_8_rows_no_crash(self):
        """
        Test: Production and business costs by elements with 8 rows.

        Previously crashed with: IndexError: index 8 is out of bounds for axis 0 with size 8

        Note: This table is in TABLES_WITHOUT_TOTAL, so should skip validation.

        Expected: No exception, returns INFO status (skipped).
        """
        df = pd.DataFrame(
            {
                "A": [
                    "Cost 1",
                    "Cost 2",
                    "Cost 3",
                    "Cost 4",
                    "Cost 5",
                    "Cost 6",
                    "Cost 7",
                    "Cost 8",
                ],
                "B": [100, 200, 300, 400, 500, 600, 700, 800],
                "C": [90, 180, 270, 360, 450, 540, 630, 720],
            }
        )

        validator = GenericTableValidator()

        # Should not raise any exception
        result = validator.validate(df, "Production and business costs by elements")

        assert result is not None
        # This table should be skipped (in TABLES_WITHOUT_TOTAL)
        assert "INFO" in result.status or "IndexError" not in result.status


class TestSCRUM6EdgeCasesBoundsChecking:
    """Additional edge case tests for bounds checking."""

    def setup_method(self):
        """Clear cache and marks before each test."""
        cross_check_cache.clear()
        cross_check_marks.clear()

    def test_empty_dataframe_no_crash(self):
        """Test that empty DataFrame doesn't crash."""
        df = pd.DataFrame()

        validator = GenericTableValidator()
        result = validator.validate(df, "test table")

        assert result is not None

    def test_single_row_table_no_crash(self):
        """Test that single-row table doesn't crash."""
        df = pd.DataFrame(
            {
                "A": ["Only row"],
                "B": [100],
                "C": [90],
            }
        )

        validator = GenericTableValidator()
        result = validator.validate(df, "test table")

        assert result is not None

    def test_two_row_table_no_crash(self):
        """Test that two-row table doesn't crash."""
        df = pd.DataFrame(
            {
                "A": ["Row 1", "Row 2"],
                "B": [100, 200],
                "C": [90, 180],
            }
        )

        validator = GenericTableValidator()
        result = validator.validate(df, "test table")

        assert result is not None

    def test_single_column_table_no_crash(self):
        """Test that single-column table doesn't crash."""
        df = pd.DataFrame(
            {
                "A": ["Row 1", "Row 2", "Row 3", "Total"],
            }
        )

        validator = GenericTableValidator()
        result = validator.validate(df, "test table")

        assert result is not None


class TestSCRUM6Form3TablesWithSmallData:
    """Test FORM_3 tables with edge case dimensions."""

    def setup_method(self):
        """Clear cache and marks before each test."""
        cross_check_cache.clear()
        cross_check_marks.clear()
        # Pre-populate cache to trigger cross-check logic
        cross_check_cache.set("investments in other entities", (1000.0, 900.0))

    def test_inventories_small_table_no_crash(self):
        """Test inventories table with minimal rows."""
        df = pd.DataFrame(
            {
                "A": ["Item", "Cost", "Allowance", "Total"],
                "B": [100, 150, 10, 240],
                "C": [90, 135, 9, 216],
            }
        )

        validator = GenericTableValidator()
        result = validator.validate(df, "inventories")

        assert result is not None
        assert "IndexError" not in result.status

    def test_bad_and_doubtful_debts_small_table_no_crash(self):
        """Test bad and doubtful debts table with minimal rows."""
        df = pd.DataFrame(
            {
                "A": ["Debtor", "Allowance", "Total"],
                "B": [500, 50, 550],
                "C": [450, 45, 495],
            }
        )

        validator = GenericTableValidator()
        result = validator.validate(df, "bad and doubtful debts")

        assert result is not None
        assert "IndexError" not in result.status

    def test_construction_in_progress_small_table_no_crash(self):
        """Test construction in progress table with minimal rows."""
        df = pd.DataFrame(
            {
                "A": ["Opening balance", "Additions", "Total"],
                "B": [1000, 500, 1500],
                "C": [900, 450, 1350],
            }
        )

        validator = GenericTableValidator()
        result = validator.validate(df, "construction in progress")

        assert result is not None
        assert "IndexError" not in result.status
