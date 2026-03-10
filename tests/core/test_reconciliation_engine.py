import pandas as pd
import pytest

from quality_audit.core.materiality import MaterialityEngine
from quality_audit.core.model.financial_model import FinancialModel
from quality_audit.core.reconciliation.reconciliation_engine import ReconciliationEngine


@pytest.fixture
def materiality_engine():
    engine = MaterialityEngine()
    return engine


@pytest.fixture
def sample_model():
    model = FinancialModel()

    # 1. Income Statement
    is_df = pd.DataFrame(
        {
            "Code": ["01", "60"],
            "Current": [1000, 200],  # Net profit 200
            "Previous": [900, 180],  # Net profit 180
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
            "Header_Code": ["110", "421"],
            "Current Year": [
                150,
                200,
            ],  # Cash 150 (variance 5 from CF), Equity Profit 200
            "Previous Year": [140, 180],  # Cash 140 (exact match), Equity Profit 180
        }
    )
    model.add_table(
        {
            "table_type": "FS_BALANCE_SHEET",
            "df": bs_df,
            "code_col": "Header_Code",
            "amount_cols": ["Current Year", "Previous Year"],
        }
    )

    # 3. Cash Flow
    cf_df = pd.DataFrame(
        {
            "Code": ["20", "70"],
            "Current": [
                50,
                149,
            ],  # Ending cash 149. BS has 150. Diff is 1 (within tolerance)
            "Previous": [40, 140],  # Ending cash 140. BS has 140. Diff is 0.
        }
    )
    model.add_table(
        {
            "table_type": "FS_CASH_FLOW",
            "df": cf_df,
            "code_col": "Code",
            "amount_cols": ["Current", "Previous"],
        }
    )

    # 4. Equity
    eq_df = pd.DataFrame(
        {"Code": ["10", "50"], "Current": [500, 200], "Previous": [450, 180]}
    )
    model.add_table(
        {
            "table_type": "FS_EQUITY",
            "df": eq_df,
            "code_col": "Code",
            "amount_cols": ["Current", "Previous"],
        }
    )

    return model


def test_reconciliation_engine_cf_bs(materiality_engine, sample_model):
    recon_engine = ReconciliationEngine(materiality_engine)
    evidence_list = recon_engine._reconcile_cf_bs_cash(sample_model)

    assert len(evidence_list) == 2

    # Current period: CF=149, BS=150. diff=1. Tolerance for RECON (Fallback 0.008) = 150.0 * 0.008 = 1.2
    assert evidence_list[0].is_material is False
    assert evidence_list[0].actual == 149.0
    assert evidence_list[0].expected == 150.0

    # Previous period: CF=140, BS=140. diff=0.
    assert evidence_list[1].is_material is False
    assert evidence_list[1].actual == 140.0
    assert evidence_list[1].expected == 140.0


def test_reconciliation_engine_is_equity(materiality_engine, sample_model):
    recon_engine = ReconciliationEngine(materiality_engine)
    evidence_list = recon_engine._reconcile_is_equity(sample_model)

    assert len(evidence_list) == 2
    assert evidence_list[0].is_material is False
    assert evidence_list[0].actual == 200.0  # Equity
    assert evidence_list[0].expected == 200.0  # IS


def test_reconciliation_engine_full(materiality_engine, sample_model):
    recon_engine = ReconciliationEngine(materiality_engine)
    evidence_list = recon_engine.reconcile(sample_model)

    # 2 for CF-BS, 2 for IS-Equity, 0 for notes
    assert len(evidence_list) == 4
    for e in evidence_list:
        assert e.is_material is False
