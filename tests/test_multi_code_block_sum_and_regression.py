"""
Tests for multi-code column exclusion in block-sum and regression scenarios.

T2: generic_block_sum_excludes_all_code_columns
T4: regression - table that previously produced "Tổng chi tiết = 26/27/31, Tổng trên bảng = 8"
"""

import pandas as pd

from quality_audit.core.validators.generic_validator import GenericTableValidator


def _make_block_sum_fixture():
    """
    Table structure that would produce wrong totals if code columns were summed:
    - Row 0: empty -> start_idx = 0.
    - Rows 1-3: detail. Code sums 26, Code.1 27, Code.2 31; 2018/2017 sum 8.
    - Row 4: empty so find_block_sum(0) breaks at i=4, end1=4.
    - Row 5: total with 2018=8, 2017=8 (compared at end1+1).
    If code columns were included we'd see "Tổng chi tiết = 26/27/31, Tổng trên bảng = 8".
    """
    return pd.DataFrame(
        [
            ["", "", "", "", "", ""],  # row 0 empty -> start_idx = 0
            ["Item A", "7", "10", "10", "2", "2"],  # row 1 detail
            ["Item B", "8", "11", "11", "3", "3"],  # row 2 detail
            ["Item C", "11", "6", "10", "3", "3"],  # row 3 detail
            ["", "", "", "", "", ""],  # row 4 empty -> find_block_sum returns end1=4
            ["Total", "", "", "", "8", "8"],  # row 5 total (end1+1)
        ],
        columns=["Description", "Code", "Code.1", "Code.2", "2018", "2017"],
    )


class TestGenericBlockSumExcludesAllCodeColumns:
    """T2: Block-sum logic must exclude all code columns; no issue must contain code-column sums."""

    def test_generic_block_sum_excludes_all_code_columns(self):
        """Detail sums must ignore Code/Code.1/Code.2; no mark with Tổng chi tiết = 26, 27, or 31."""
        df = _make_block_sum_fixture()

        validator = GenericTableValidator()
        result = validator.validate(df, heading="other payables")

        # No issue or mark should contain "Tổng chi tiết = 26" or "27" or "31" (code-column sums)
        all_text = " ".join(str(m.get("comment", "")) for m in result.marks)
        assert "Tổng chi tiết = 26" not in all_text, (
            "Block sum must not include Code column in Tổng chi tiết"
        )
        assert "Tổng chi tiết = 27" not in all_text, (
            "Block sum must not include Code.1 in Tổng chi tiết"
        )
        assert "Tổng chi tiết = 31" not in all_text, (
            "Block sum must not include Code.2 in Tổng chi tiết"
        )


class TestMultiCodeRegressionTotals:
    """T4: Regression - pattern 'Tổng chi tiết = 26/27/31, Tổng trên bảng = 8' must not appear after fix."""

    def test_focus_list_no_code_based_totals(self):
        """After multi-code exclusion, totals fail only on amount columns; no code-column vs amount total mismatch."""
        df = _make_block_sum_fixture()

        validator = GenericTableValidator()
        result = validator.validate(df, heading="other payables")

        # Pattern that indicated the bug: "Tổng chi tiết = X, Tổng trên bảng = 8" with X in {26,27,31}
        issue_comments = [
            str(m.get("comment", "")) for m in result.marks if m.get("comment")
        ]
        for issue in issue_comments:
            assert "Tổng trên bảng = 8" not in issue or "Tổng chi tiết = 8" in issue, (
                "If total on table is 8, detail sum must be 8 (amounts only), not 26/27/31"
            )
        for m in result.marks:
            comment = str(m.get("comment", ""))
            if "Tổng trên bảng = 8" in comment:
                assert "Tổng chi tiết = 8" in comment, (
                    "When total on table is 8, detail sum in comment must be 8 (amount cols only)"
                )
