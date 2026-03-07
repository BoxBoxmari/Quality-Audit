import pandas as pd

from quality_audit.core.materiality import MaterialityEngine
from quality_audit.core.model.statement_model_builder import StatementModel
from quality_audit.core.rules.cash_flow_rules import CashFlowRules


def _build_cash_flow_model() -> StatementModel:
    model = StatementModel("FS_CASH_FLOW")
    df = pd.DataFrame(
        {
            "Code": ["21", "22", "23", "24", "25", "26", "27", "30"],
            "Description": [
                "Investing 21",
                "Investing 22",
                "Investing 23",
                "Investing 24",
                "Investing 25",
                "Investing 26",
                "Investing 27",
                "Net investing cash flow",
            ],
            "CY": [10.0, 20.0, 30.0, -5.0, 15.0, 25.0, 5.0, 100.0],
        }
    )
    model.add_table(
        {
            "df": df,
            "table_type": "FS_CASH_FLOW",
            "table_id": "tbl_cf_test",
            "code_col": "Code",
            "amount_cols": ["CY"],
        }
    )
    return model


def test_cash_flow_code_30_formula_evaluates_without_name_error():
    model = _build_cash_flow_model()
    rule = CashFlowRules()
    materiality = MaterialityEngine()

    evidence = rule.evaluate_model(model, materiality=materiality)

    code_30_evidence = [e for e in evidence if "Code 30 [CY]" in e.assertion_text]
    assert len(code_30_evidence) == 1


def test_cash_flow_code_30_formula_expected_and_actual_match():
    model = _build_cash_flow_model()
    rule = CashFlowRules()
    materiality = MaterialityEngine()

    evidence = rule.evaluate_model(model, materiality=materiality)
    code_30 = next(e for e in evidence if "Code 30 [CY]" in e.assertion_text)

    assert code_30.expected == 100.0
    assert code_30.actual == 100.0
    assert code_30.diff == 0.0
