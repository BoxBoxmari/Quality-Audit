import pandas as pd
import pytest

from quality_audit.core.model.financial_model import FinancialModel


@pytest.fixture
def sample_financial_model():
    model = FinancialModel()

    # 1. Income Statement
    is_df = pd.DataFrame(
        {
            "Code": ["01", "02", "11", "20"],
            "Current": [1000, 100, 400, 500],
            "Previous": [900, 90, 350, 460],
        }
    )
    model.add_table(
        {
            "table_type": "FS_INCOME_STATEMENT",
            "df": is_df,
            "code_col": "Code",
            "amount_cols": ["Current", "Previous"],
        }
    )

    # 2. Balance Sheet
    bs_df = pd.DataFrame(
        {
            "Header_Code": ["110", "270", "300", "400", "440"],
            "Col1": [5000, 15000, 8000, 7000, 15000],
            "Col2": [4500, 14000, 7500, 6500, 14000],
        }
    )
    model.add_table(
        {
            "table_type": "FS_BALANCE_SHEET",
            "df": bs_df,
            "code_col": "Header_Code",
            "amount_cols": ["Col1", "Col2"],
        }
    )

    # 3. Notes
    note_df = pd.DataFrame(
        {
            "CT": ["Item A", "Item B", "Total"],
            "Mã số": ["01", "02", "10"],
            "Value1": [100, 200, 300],
            "Value2": [50, 60, 110],
        }
    )
    model.add_table(
        {
            "table_type": "GENERIC_NOTE",
            "df": note_df,
            "code_col": "Mã số",
            "amount_cols": ["Value1", "Value2"],
        }
    )

    return model


def test_financial_model_add_table(sample_financial_model):
    assert len(sample_financial_model.income_statements) == 1
    assert len(sample_financial_model.balance_sheets) == 1
    assert len(sample_financial_model.cash_flows) == 0
    assert len(sample_financial_model.equity_changes) == 0
    assert len(sample_financial_model.notes) == 1


def test_financial_model_get_line_item(sample_financial_model):
    # Test getting IS item (Current year)
    val = sample_financial_model.get_line_item("FS_INCOME_STATEMENT", "20", col_idx=0)
    assert val == 500.0

    # Test getting IS item (Previous year)
    val = sample_financial_model.get_line_item("FS_INCOME_STATEMENT", "20", col_idx=1)
    assert val == 460.0

    # Test single-digit normalization
    val = sample_financial_model.get_line_item("FS_INCOME_STATEMENT", "1", col_idx=0)
    assert val == 1000.0

    # Test Balance Sheet
    val = sample_financial_model.get_line_item("FS_BALANCE_SHEET", "270", col_idx=0)
    assert val == 15000.0

    # Test Notes
    val = sample_financial_model.get_line_item("NOTE", "10", col_idx=0)
    assert val == 300.0


def test_financial_model_get_line_item_not_found(sample_financial_model):
    # Unknown statement type
    val = sample_financial_model.get_line_item("UNKNOWN_TYPE", "20")
    assert val is None

    # Code not found
    val = sample_financial_model.get_line_item("FS_INCOME_STATEMENT", "99")
    assert val is None

    # Column out of bounds
    val = sample_financial_model.get_line_item("FS_INCOME_STATEMENT", "20", col_idx=5)
    assert val is None
