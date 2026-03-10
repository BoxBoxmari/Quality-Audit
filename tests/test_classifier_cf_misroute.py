"""
Regression test: CF sub-table codes must classify as FS_CASH_FLOW, not FS_INCOME_STATEMENT.
Covers P3 fix: IS fallback guarded by cf_exclusive_matches == 0.
"""

import pandas as pd
import pytest

from quality_audit.core.classification.table_classifier_v2 import TableClassifierV2
from quality_audit.core.routing.table_type_classifier import TableType


class TestCFSubTableMisroute:
    @pytest.fixture
    def classifier(self):
        return TableClassifierV2()

    def test_cf_codes_with_cf_exclusive_classifies_as_cash_flow(self, classifier):
        """Table with CF-exclusive code 03 plus shared codes 21,27,30 → FS_CASH_FLOW."""
        rows = [
            ["03", "Depreciation"],
            ["21", "Purchase of fixed assets"],
            ["27", "Proceeds from disposal"],
            ["30", "Net cash from investing"],
        ]
        df = pd.DataFrame(rows, columns=["Code", "Description"])
        result = classifier.classify(df, heading=None)
        assert result.table_type == TableType.FS_CASH_FLOW, (
            f"Expected FS_CASH_FLOW but got {result.table_type}"
        )

    def test_shared_codes_21_27_30_not_misrouted_to_is(self, classifier):
        """Table with codes {21,27,30} having CF-exclusive 27 → must NOT be IS."""
        rows = [
            ["21", "Purchase of fixed assets"],
            ["27", "Proceeds from disposal of investments"],
            ["30", "Net cash from investing activities"],
        ]
        df = pd.DataFrame(rows, columns=["Code", "Description"])
        result = classifier.classify(df, heading=None)
        # 27 is CF-exclusive → IS fallback should be blocked
        assert result.table_type != TableType.FS_INCOME_STATEMENT, (
            f"Should NOT be IS but got {result.table_type}"
        )

    def test_is_codes_with_is_exclusive_classifies_as_income_statement(
        self, classifier
    ):
        """Table with IS-exclusive code 51 plus shared codes 10,20,30 → FS_INCOME_STATEMENT."""
        rows = [
            ["10", "Revenue"],
            ["20", "Cost of goods sold"],
            ["30", "Gross profit"],
            ["51", "Interest expense"],
        ]
        df = pd.DataFrame(rows, columns=["Code", "Description"])
        result = classifier.classify(df, heading=None)
        assert result.table_type == TableType.FS_INCOME_STATEMENT, (
            f"Expected FS_INCOME_STATEMENT but got {result.table_type}"
        )

    def test_mixed_codes_no_exclusives_uses_count_ratio(self, classifier):
        """Table with only shared codes (no exclusives) → classifier uses count ratio."""
        rows = [
            ["10", "Item A"],
            ["20", "Item B"],
        ]
        df = pd.DataFrame(rows, columns=["Code", "Description"])
        result = classifier.classify(df, heading=None)
        # Both IS and CF contain codes 10, 20 — no exclusives either way.
        # Acceptable: IS or CF, just not UNKNOWN
        assert result.table_type in (
            TableType.FS_INCOME_STATEMENT,
            TableType.FS_CASH_FLOW,
        )
