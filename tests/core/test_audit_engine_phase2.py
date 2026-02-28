"""
Tests for Phase 2 classification modules:
  - StructuralFingerprinter
  - TableClassifierV2
  - Shadow mode integration
"""

import pandas as pd
import pytest

from quality_audit.core.classification import (
    StructuralFingerprint,
    StructuralFingerprinter,
    TableClassifierV2,
)
from quality_audit.core.routing.table_type_classifier import TableType


# ---------------------------------------------------------------------------
# Helper: build a minimal DataFrame from row dicts
# ---------------------------------------------------------------------------


def _make_table(rows):
    """Build DataFrame from list of dicts."""
    return pd.DataFrame(rows)


# ---------------------------------------------------------------------------
# StructuralFingerprinter
# ---------------------------------------------------------------------------


class TestStructuralFingerprinter:
    def test_empty_table(self):
        fp = StructuralFingerprinter()
        result = fp.extract(pd.DataFrame())
        assert result.total_rows == 0
        assert result.code_density == 0.0
        assert result.bs_code_matches == 0

    def test_balance_sheet_codes(self):
        rows = [
            {"Code": "100", "Item": "Total current assets", "Amount": 1000},
            {"Code": "110", "Item": "Cash", "Amount": 500},
            {"Code": "120", "Item": "Receivables", "Amount": 300},
            {"Code": "270", "Item": "Total assets", "Amount": 1000},
            {"Code": "300", "Item": "Total liabilities", "Amount": 600},
        ]
        fp = StructuralFingerprinter()
        result = fp.extract(_make_table(rows))
        assert result.bs_code_matches >= 5
        assert result.code_density > 0.5
        assert "100" in result.found_codes
        assert "assets" in result.keywords_found

    def test_income_statement_codes(self):
        rows = [
            {"Code": "01", "Item": "Revenue from sales", "Amount": 5000},
            {"Code": "11", "Item": "Cost of sales", "Amount": 3000},
            {"Code": "20", "Item": "Gross profit", "Amount": 2000},
            {"Code": "25", "Item": "Admin expenses", "Amount": 500},
            {"Code": "50", "Item": "Net profit", "Amount": 1500},
        ]
        fp = StructuralFingerprinter()
        result = fp.extract(_make_table(rows))
        assert result.is_code_matches >= 4
        assert result.is_exclusive_matches >= 1  # code 25

    def test_cash_flow_codes(self):
        rows = [
            {"Code": "01", "Item": "Cash flows from operating", "Amount": 100},
            {"Code": "08", "Item": "Depreciation", "Amount": 50},
            {"Code": "20", "Item": "Operating cash flow", "Amount": 150},
            {"Code": "30", "Item": "Investing activities", "Amount": -80},
            {"Code": "50", "Item": "Net cash increase", "Amount": 70},
        ]
        fp = StructuralFingerprinter()
        result = fp.extract(_make_table(rows))
        assert result.cf_code_matches >= 4
        assert result.cf_exclusive_matches >= 1  # code 08
        assert "cash" in result.keywords_found

    def test_movement_structure(self):
        rows = [
            {"Item": "Opening balance", "Amount": 1000},
            {"Item": "Additions during year", "Amount": 200},
            {"Item": "Depreciation charge", "Amount": -100},
            {"Item": "Disposal", "Amount": -50},
            {"Item": "Closing balance", "Amount": 1050},
        ]
        fp = StructuralFingerprinter()
        result = fp.extract(_make_table(rows))
        assert result.has_opening is True
        assert result.has_closing is True
        assert result.movement_row_count >= 2
        assert result.has_movement_structure is True

    def test_no_movement_without_closing(self):
        rows = [
            {"Item": "Opening balance", "Amount": 1000},
            {"Item": "Addition", "Amount": 200},
        ]
        fp = StructuralFingerprinter()
        result = fp.extract(_make_table(rows))
        assert result.has_opening is True
        assert result.has_closing is False
        assert result.has_movement_structure is False

    def test_keyword_score(self):
        rows = [
            {"Item": "Total assets", "Amount": 100},
            {"Item": "Total liabilities", "Amount": 50},
            {"Item": "Total equity", "Amount": 50},
        ]
        fp = StructuralFingerprinter()
        result = fp.extract(_make_table(rows))
        assert "assets" in result.keywords_found
        assert "liabilities" in result.keywords_found
        assert "equity" in result.keywords_found
        assert result.keyword_score > 0.2


# ---------------------------------------------------------------------------
# TableClassifierV2
# ---------------------------------------------------------------------------


class TestTableClassifierV2:
    def test_empty_table(self):
        clf = TableClassifierV2()
        result = clf.classify(pd.DataFrame(), "Balance Sheet")
        assert result.table_type == TableType.UNKNOWN
        assert result.context["classifier_version"] == "v2"

    def test_balance_sheet_by_heading_and_codes(self):
        rows = [
            {"Code": "100", "Item": "Current assets", "Amount": 1000},
            {"Code": "110", "Item": "Cash", "Amount": 500},
            {"Code": "270", "Item": "Total assets", "Amount": 1000},
            {"Code": "300", "Item": "Liabilities", "Amount": 600},
        ]
        clf = TableClassifierV2()
        result = clf.classify(_make_table(rows), "Balance Sheet")
        assert result.table_type == TableType.FS_BALANCE_SHEET
        assert result.confidence > 0.7

    def test_income_statement_by_codes_and_keywords(self):
        rows = [
            {"Code": "01", "Item": "Revenue from sales", "Amount": 5000},
            {"Code": "11", "Item": "Cost of sales", "Amount": 3000},
            {"Code": "20", "Item": "Gross profit", "Amount": 2000},
            {"Code": "25", "Item": "Admin expenses", "Amount": 500},
            {"Code": "50", "Item": "Net profit", "Amount": 1500},
        ]
        clf = TableClassifierV2()
        result = clf.classify(_make_table(rows), "Statement of Income")
        assert result.table_type == TableType.FS_INCOME_STATEMENT
        assert result.confidence > 0.7

    def test_cash_flow_classification(self):
        rows = [
            {"Code": "01", "Item": "Cash flows from operating", "Amount": 100},
            {"Code": "08", "Item": "Depreciation charged", "Amount": 50},
            {"Code": "20", "Item": "Net operating cash flows", "Amount": 150},
            {"Code": "30", "Item": "Investing activities cash flow", "Amount": -80},
            {"Code": "50", "Item": "Net cash increase", "Amount": 70},
        ]
        clf = TableClassifierV2()
        result = clf.classify(_make_table(rows), "Statement of Cash Flows")
        assert result.table_type == TableType.FS_CASH_FLOW

    def test_generic_note_fallback(self):
        rows = [
            {"Item": "Accrued expenses", "Amount": 100},
            {"Item": "Audit fees", "Amount": 20},
            {"Item": "Legal fees", "Amount": 30},
        ]
        clf = TableClassifierV2()
        result = clf.classify(_make_table(rows), "Accrued expenses")
        assert result.table_type == TableType.GENERIC_NOTE

    def test_negative_keyword_forces_note(self):
        rows = [
            {"Code": "100", "Item": "Assets", "Amount": 1000},
            {"Code": "110", "Item": "Cash", "Amount": 500},
        ]
        clf = TableClassifierV2()
        result = clf.classify(_make_table(rows), "Details of balance sheet items")
        # "details of" is negative keyword → should route to note
        assert result.table_type in (TableType.GENERIC_NOTE, TableType.UNKNOWN)

    def test_skipped_heading(self):
        clf = TableClassifierV2()
        result = clf.classify(_make_table([{"A": 1}]), "SKIPPED_FOOTER")
        assert result.table_type == TableType.UNKNOWN

    def test_classifier_version_in_context(self):
        clf = TableClassifierV2()
        result = clf.classify(_make_table([{"A": 1}]), "Some heading")
        assert result.context["classifier_version"] == "v2"

    def test_structure_override_no_heading(self):
        """V2 should classify by structure even with no heading."""
        rows = [
            {"Code": "100", "Item": "Current assets", "Amount": 1000},
            {"Code": "110", "Item": "Cash", "Amount": 500},
            {"Code": "150", "Item": "Inventories", "Amount": 200},
            {"Code": "270", "Item": "Total assets", "Amount": 1000},
            {"Code": "300", "Item": "Liabilities", "Amount": 600},
            {"Code": "440", "Item": "Total L+E", "Amount": 1000},
        ]
        clf = TableClassifierV2()
        result = clf.classify(_make_table(rows), None)
        assert result.table_type == TableType.FS_BALANCE_SHEET
