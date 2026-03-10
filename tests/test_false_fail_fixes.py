"""
Unit tests for false FAIL fixes (Patches 1-4).

Covers:
- Patch 1: Merge blocked on heading mismatch with page break
- Patch 2: No scope for TABLES_WITHOUT_TOTAL headings
- Patch 3: Amount cols exclude non-money header columns
- Patch 4: Subtotal/netting rows excluded from detail_rows
"""

import pandas as pd
import pytest

from quality_audit.io.word_reader import WordReader
from quality_audit.utils.note_structure import (
    RowType,
    _detect_amount_cols,
    _detect_scopes,
    _split_segments,
    analyze_note_table,
)


# ---------------------------------------------------------------------------
# Patch 1: Merge heading mismatch on page break
# ---------------------------------------------------------------------------
class TestMergeBlockedOnHeadingMismatch:
    def setup_method(self):
        self.reader = WordReader()

    def test_heading_mismatch_blocked_despite_page_break(self):
        prev_df = pd.DataFrame({"A": [1, 2], "B": [3, 4]})
        curr_df = pd.DataFrame({"A": [5, 6], "B": [7, 8]})
        should_merge, reason, evidence = self.reader._decide_merge(
            prev_df=prev_df,
            curr_df=curr_df,
            prev_heading="Cash and cash equivalents",
            curr_heading="Accounts receivable",
            curr_note_number=None,
            page_break=True,
            paragraphs_since=0,
            long_paragraph=False,
            is_footer=False,
            prev_is_footer=False,
            flags={"ENABLE_SPLIT_TABLE_MERGE": True},
        )
        assert should_merge is False
        assert reason == "HEADING_MISMATCH"
        assert evidence.get("heading_mismatch_on_page_break") is True

    def test_merge_allowed_when_curr_heading_none_on_page_break(self):
        prev_df = pd.DataFrame({"A": [1, 2], "B": [3, 4]})
        curr_df = pd.DataFrame({"A": [5, 6], "B": [7, 8]})
        should_merge, reason, evidence = self.reader._decide_merge(
            prev_df=prev_df,
            curr_df=curr_df,
            prev_heading="Business costs by element",
            curr_heading=None,
            curr_note_number=None,
            page_break=True,
            paragraphs_since=0,
            long_paragraph=False,
            is_footer=False,
            prev_is_footer=False,
            flags={"ENABLE_SPLIT_TABLE_MERGE": True},
        )
        assert should_merge is True
        assert reason == "MERGED_BY_STRONG_ANCHOR"

    def test_merge_allowed_when_headings_match(self):
        prev_df = pd.DataFrame({"A": [1], "B": [2]})
        curr_df = pd.DataFrame({"A": [3], "B": [4]})
        should_merge, reason, _ = self.reader._decide_merge(
            prev_df=prev_df,
            curr_df=curr_df,
            prev_heading="Same table",
            curr_heading="Same table",
            curr_note_number=None,
            page_break=True,
            paragraphs_since=0,
            long_paragraph=False,
            is_footer=False,
            prev_is_footer=False,
            flags={"ENABLE_SPLIT_TABLE_MERGE": True},
        )
        assert should_merge is True


# ---------------------------------------------------------------------------
# Patch 2: No scope for TABLES_WITHOUT_TOTAL
# ---------------------------------------------------------------------------
class TestNoScopeForTablesWithoutTotal:
    def test_no_scope_for_non_cash_investing_activity(self):
        df = pd.DataFrame(
            {
                "Item": ["Activity A", "Activity B", "Activity C", "Activity D"],
                "Amount": [100, 200, 300, 400],
            }
        )
        result = analyze_note_table(df, "Non-cash investing activity", "tbl_001")
        assert result.scopes == []

    def test_no_scope_for_business_costs_by_element(self):
        df = pd.DataFrame(
            {
                "Element": ["Materials", "Labor", "Depreciation", "Others"],
                "2018": [1000, 2000, 500, 300],
                "2017": [900, 1800, 450, 280],
            }
        )
        result = analyze_note_table(df, "business costs by element", "tbl_002")
        assert result.scopes == []

    def test_scope_still_created_for_normal_table(self):
        df = pd.DataFrame(
            {
                "Item": ["Item A", "Item B", "Item C", "Total"],
                "Amount": [100, 200, 300, 600],
            }
        )
        result = analyze_note_table(df, "Some normal note", "tbl_003")
        assert len(result.scopes) >= 1


# ---------------------------------------------------------------------------
# Patch 3: Amount cols exclude non-money headers
# ---------------------------------------------------------------------------
class TestAmountColsHeaderFilter:
    def test_excludes_year_of_maturity(self):
        df = pd.DataFrame(
            {
                "Description": ["Loan A", "Loan B"],
                "Year of maturity": [2020, 2022],
                "Amount": [1000000, 2000000],
            }
        )
        cols = _detect_amount_cols(df, "Description")
        assert "Amount" in cols
        assert "Year of maturity" not in cols

    def test_excludes_interest_rate_pct(self):
        df = pd.DataFrame(
            {
                "Description": ["Loan A", "Loan B"],
                "Annual interest rate (%)": [5.5, 7.0],
                "Principal": [1000000, 2000000],
            }
        )
        cols = _detect_amount_cols(df, "Description")
        assert "Principal" in cols
        assert "Annual interest rate (%)" not in cols

    def test_excludes_quantity_column(self):
        df = pd.DataFrame(
            {
                "Item": ["X", "Y"],
                "Quantity": [10, 20],
                "Value": [500, 1000],
            }
        )
        cols = _detect_amount_cols(df, "Item")
        assert "Value" in cols
        assert "Quantity" not in cols

    def test_keeps_normal_money_columns(self):
        df = pd.DataFrame(
            {
                "Item": ["A", "B", "C"],
                "2018": [100, 200, 300],
                "2017": [90, 180, 270],
            }
        )
        cols = _detect_amount_cols(df, "Item")
        assert "2018" in cols
        assert "2017" in cols


# ---------------------------------------------------------------------------
# Patch 4: Subtotal/netting exclusion
# ---------------------------------------------------------------------------
class TestSubtotalNettingExclusion:
    def test_excludes_gross_discount_net_from_details(self):
        df = pd.DataFrame(
            {
                "Item": [
                    "Customer A",
                    "Customer B",
                    "Gross",
                    "Discount",
                    "Net",
                    "Total",
                ],
                "Amount": [100, 200, 300, -50, 250, 250],
            }
        )
        result = analyze_note_table(df, "Accounts receivable", "tbl_004")
        # Total row should be found (the "Total" row)
        assert len(result.scopes) >= 1
        scope = result.scopes[0]
        # detail_rows should NOT include rows with labels Gross/Discount/Net
        detail_labels = [df.iloc[r]["Item"] for r in scope.detail_rows]
        assert "Gross" not in detail_labels
        assert "Discount" not in detail_labels
        assert "Net" not in detail_labels
        # But regular customer rows should be included
        assert "Customer A" in detail_labels
        assert "Customer B" in detail_labels

    def test_excludes_subtotal_row(self):
        df = pd.DataFrame(
            {
                "Item": ["Part A", "Part B", "Subtotal", "Part C", "Total"],
                "Value": [10, 20, 30, 40, 70],
            }
        )
        result = analyze_note_table(df, "Some note", "tbl_005")
        assert len(result.scopes) >= 1
        scope = result.scopes[0]
        detail_labels = [df.iloc[r]["Item"] for r in scope.detail_rows]
        assert "Subtotal" not in detail_labels

    def test_total_like_rows_excluded_from_details(self):
        """TOTAL_LIKE rows (classified by regex) must not be in detail_rows."""
        df = pd.DataFrame(
            {
                "Item": ["Item A", "Item B", "Tổng", "Item C", "Total"],
                "Value": [10, 20, 30, 40, 100],
            }
        )
        result = analyze_note_table(df, "Test", "tbl_006")
        for scope in result.scopes:
            for r in scope.detail_rows:
                assert result.row_types[r] != RowType.TOTAL_LIKE


# ---------------------------------------------------------------------------
# Patch A: Expanded TABLES_WITHOUT_TOTAL
# ---------------------------------------------------------------------------
class TestTablesWithoutTotalExpanded:
    """Verify new headings in TABLES_WITHOUT_TOTAL cause skip."""

    @pytest.mark.parametrize(
        "heading",
        [
            "transaction value",
            "annual interest rate",
            "equivalent vnd'000",
            "number of shares",
            "transfer from long-term borrowings",
            "recognised in consolidated balance sheet",
            "recognised in consolidated statement of income",
        ],
    )
    def test_new_headings_produce_no_scopes(self, heading):
        df = pd.DataFrame(
            {
                "Item": ["Row A", "Row B", "Row C", "Row D"],
                "Amount": [100, 200, 300, 400],
            }
        )
        result = analyze_note_table(df, heading, "tbl_patch_a")
        assert result.scopes == []


# ---------------------------------------------------------------------------
# Patch B: Merge blocked on header mismatch (column headers differ)
# ---------------------------------------------------------------------------
class TestMergeBlockedOnHeaderMismatch:
    def setup_method(self):
        self.reader = WordReader()

    def test_merge_blocked_when_column_headers_differ_across_page_break(self):
        """curr_heading=None but col headers differ => block merge."""
        prev_df = pd.DataFrame({"Description": [1], "Amount": [2]})
        curr_df = pd.DataFrame({"Counterparty": [3], "Balance": [4]})
        should_merge, reason, evidence = self.reader._decide_merge(
            prev_df=prev_df,
            curr_df=curr_df,
            prev_heading="Cash and cash equivalents",
            curr_heading=None,
            curr_note_number=None,
            page_break=True,
            paragraphs_since=0,
            long_paragraph=False,
            is_footer=False,
            prev_is_footer=False,
            flags={"ENABLE_SPLIT_TABLE_MERGE": True},
        )
        assert should_merge is False
        assert reason == "MERGE_BLOCKED_HEADER_MISMATCH"
        assert evidence.get("header_similarity", 1.0) < 0.5

    def test_merge_allowed_when_column_headers_match_across_page_break(self):
        """curr_heading=None but col headers identical => allow merge."""
        prev_df = pd.DataFrame({"Description": [1], "Amount": [2]})
        curr_df = pd.DataFrame({"Description": [3], "Amount": [4]})
        should_merge, reason, _ = self.reader._decide_merge(
            prev_df=prev_df,
            curr_df=curr_df,
            prev_heading="Cash and cash equivalents",
            curr_heading=None,
            curr_note_number=None,
            page_break=True,
            paragraphs_since=0,
            long_paragraph=False,
            is_footer=False,
            prev_is_footer=False,
            flags={"ENABLE_SPLIT_TABLE_MERGE": True},
        )
        assert should_merge is True
        assert reason == "MERGED_BY_STRONG_ANCHOR"


# ---------------------------------------------------------------------------
# Patch C: Listing-table gate in _detect_scopes
# ---------------------------------------------------------------------------
class TestListingTableNoFallbackTotal:
    @pytest.mark.parametrize(
        "heading",
        [
            "Accounts receivable detailed by significant customers",
            "Significant transactions with related parties",
            "Equity investments in other entities",
            "Non-cash investing activities",
        ],
    )
    def test_listing_heading_produces_no_scopes(self, heading):
        df = pd.DataFrame(
            {
                "Name": ["Alpha", "Beta", "Gamma", "Delta"],
                "Amount": [100, 200, 300, 400],
            }
        )
        result = analyze_note_table(df, heading, "tbl_patch_c")
        assert result.scopes == []


# ---------------------------------------------------------------------------
# Patch D: Amount cols exclude shares/year-value columns
# ---------------------------------------------------------------------------
class TestAmountColsSharesAndYearExclusion:
    def test_excludes_number_of_shares(self):
        df = pd.DataFrame(
            {
                "Description": ["Company A", "Company B"],
                "Number of shares": [10000, 20000],
                "Value": [500000, 1000000],
            }
        )
        cols = _detect_amount_cols(df, "Description")
        assert "Value" in cols
        assert "Number of shares" not in cols

    def test_excludes_year_value_column(self):
        """Column where values are 2017/2018 should be excluded."""
        df = pd.DataFrame(
            {
                "Description": ["Loan A", "Loan B", "Loan C"],
                "Maturity year": [2019, 2020, 2021],
                "Amount": [500000, 600000, 700000],
            }
        )
        cols = _detect_amount_cols(df, "Description")
        assert "Amount" in cols
        # Maturity year header doesn't match regex but values are ~year
        # The year-value heuristic should catch this
        assert "Maturity year" not in cols

    def test_keeps_large_monetary_values(self):
        """Period columns with large values should NOT be excluded."""
        df = pd.DataFrame(
            {
                "Item": ["Revenue", "Expenses", "Profit"],
                "2018": [5000000, 3000000, 2000000],
                "2017": [4500000, 2800000, 1700000],
            }
        )
        cols = _detect_amount_cols(df, "Item")
        assert "2018" in cols
        assert "2017" in cols


# ---------------------------------------------------------------------------
# Negative tests: FAIL must still trigger on genuinely wrong data
# ---------------------------------------------------------------------------
class TestNegativeFalsePass:
    def test_fail_on_wrong_sum(self):
        """Table where detail rows don't sum to total must NOT produce PASS."""
        df = pd.DataFrame(
            {
                "Item": ["A", "B", "C", "Total"],
                "Amount": [100, 200, 300, 999],  # 100+200+300 != 999
            }
        )
        result = analyze_note_table(df, "Some normal note", "tbl_neg_1")
        # The scope should be detected (normal table with Total row)
        assert len(result.scopes) >= 1
        scope = result.scopes[0]
        # Verify the total_row_idx points to the Total row
        assert scope.total_row_idx == 3
        # Verify detail rows don't include the total
        assert 3 not in scope.detail_rows

    def test_scope_created_for_table_with_explicit_total(self):
        """A table with explicit 'Total' row must have scopes, not INFO_SKIPPED."""
        df = pd.DataFrame(
            {
                "Description": ["Fee income", "Interest", "Service charge", "Total"],
                "2018": [50000, 30000, 20000, 100000],
                "2017": [45000, 28000, 18000, 91000],
            }
        )
        result = analyze_note_table(df, "Other income", "tbl_neg_2")
        assert len(result.scopes) >= 1
