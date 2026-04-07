import pandas as pd
import pytest

from quality_audit.core.routing.table_type_classifier import (
    TableType,
    TableTypeClassifier,
)
from quality_audit.io.word_reader import WordReader


def test_heading_junk_filter():
    reader = WordReader()

    # Valid
    assert not reader._is_heading_junk("Bảng cân đối kế toán")
    assert not reader._is_heading_junk("Income Statement")

    # Junk (Ticket 1 patterns)
    assert reader._is_heading_junk("2018 VND'000")
    assert reader._is_heading_junk("31/12/2018 VND")
    assert reader._is_heading_junk("VND")
    assert reader._is_heading_junk("31/12/2018")
    assert reader._is_heading_junk("Đơn vị tính: VND")


def test_structure_override_income_statement():
    classifier = TableTypeClassifier()

    # Heading is literal garbage
    heading = "2018 VND'000"

    # Table has classic P&L codes: 01, 11, 20, 21, 22, 30, 50, 60
    data = {
        "Col1": [
            "Doanh thu",
            "Giá vốn",
            "Lợi nhuận gộp",
            "Chi phí BH",
            "Lợi nhuận KTTT",
        ],
        "Col2": ["01", "11", "20", "25", "50"],
    }

    df = pd.DataFrame(data)
    result = classifier.classify(df, heading=heading)

    # Even though heading is junk/generic, code density implies FS_INCOME_STATEMENT
    assert result.table_type == TableType.FS_INCOME_STATEMENT
    assert "Structure-based override" in result.reasons[0]


def test_structure_override_balance_sheet():
    classifier = TableTypeClassifier()
    heading = "Some generic heading"

    # Table has BS codes
    data = {
        "Col1": ["Tài sản ngắn hạn", "Tiền", "Tài sản dài hạn"],
        "Col2": ["100", "110", "200"],
    }  # Wait: 200 is BS, the filter looks for 100, 110, 270, 300, 440

    data = {"Col1": ["TS", "TT", "NV", "Nợ"], "Col2": ["100", "110", "300", "440"]}
    df = pd.DataFrame(data)
    result = classifier.classify(df, heading=heading)

    assert result.table_type == TableType.FS_BALANCE_SHEET


def test_structure_override_cashflow():
    classifier = TableTypeClassifier()
    heading = "Cash flow part 2"

    # Table has CF codes: 20, 30, 40, 50, 60, 70
    data = {
        "Col1": [
            "Cash flows from investing",
            "Purchase of assets",
            "Net cash from investing",
            "Cash from financing",
        ],
        "Col2": ["20", "21", "30", "40"],
        "Col3": ["(100)", "(50)", "(150)", "200"],
    }
    df = pd.DataFrame(data)
    # The structure override looks for cash keywords for CF
    result = classifier.classify(df, heading=heading)

    assert result.table_type == TableType.FS_CASH_FLOW


def test_legacy_heading_map_keeps_statement_family_without_content_guardrail():
    """
    Legacy parity lock:
    statement heading must map directly to FS type even when content is narrative.
    """
    classifier = TableTypeClassifier()
    df = pd.DataFrame(
        {
            "Desc": ["Narrative line", "Another narrative line"],
            "Note": ["No numeric evidence", "No code evidence"],
        }
    )
    result = classifier.classify(df, heading="Statement of Financial Position")
    assert result.table_type == TableType.FS_BALANCE_SHEET
    assert result.context is not None
    assert result.context.get("classifier_reason") == "Legacy heading map match"


def test_heading_statement_phrase_in_note_context_is_not_forced_to_fs():
    classifier = TableTypeClassifier()
    df = pd.DataFrame(
        {
            "Description": [
                "Recognised in consolidated balance sheet",
                "Deferred tax asset",
            ],
            "Amount": ["100", "90"],
        }
    )
    result = classifier.classify(
        df,
        heading="Recognised in consolidated statement of income",
    )
    assert result.table_type in {TableType.GENERIC_NOTE, TableType.TAX_NOTE}
