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


def _build_cash_flow_model_with_shifted_code_09() -> StatementModel:
    """Build a model where code 09 appears in a non-code column."""
    model = StatementModel("FS_CASH_FLOW")
    df = pd.DataFrame(
        {
            "Code": ["08", "", "20"],
            "Description": [
                "Depreciation and amortisation",
                "Change in receivables and other current assets",
                "Net cash from operating activities",
            ],
            # Simulate misalignment: the code "9" lands in a neighbour column
            # instead of the detected code column.
            "Other": ["", "9", ""],
            "CY": [50.0, 30.0, 80.0],
        }
    )
    model.add_table(
        {
            "df": df,
            "table_type": "FS_CASH_FLOW",
            "table_id": "tbl_cf_shifted",
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


def test_statement_model_recovers_shifted_code_09():
    model = _build_cash_flow_model_with_shifted_code_09()
    rows_09 = model.find_code("09")
    assert len(rows_09) == 1
    assert rows_09[0].values["CY"] == 30.0


def test_cash_flow_code_20_includes_shifted_code_09():
    model = _build_cash_flow_model_with_shifted_code_09()
    rule = CashFlowRules()
    materiality = MaterialityEngine()

    evidence = rule.evaluate_model(model, materiality=materiality)
    code_20 = next(e for e in evidence if "CF Formula Code 20 [CY]" in e.assertion_text)

    assert code_20.expected == 80.0
    assert code_20.actual == 80.0
    assert code_20.diff == 0.0


def _build_cf_code20_subtotal_without_code() -> StatementModel:
    """T5 fixture: subtotal row between 12 and 14 has no code (empty); Code 20 = 08+09+10+11+12+14+15+17."""
    model = StatementModel("FS_CASH_FLOW")
    df = pd.DataFrame(
        {
            "Code": ["08", "09", "10", "11", "12", "", "14", "15", "17", "20"],
            "Description": [
                "Depreciation",
                "Change receivables",
                "Other 10",
                "Other 11",
                "Other 12",
                "Cash generated from operations",
                "Interest paid",
                "Tax paid",
                "Other 17",
                "Net cash from operating activities",
            ],
            "CY": [10.0, 5.0, 3.0, 4.0, 5.0, 27.0, 6.0, 7.0, 8.0, 48.0],
        }
    )
    # 08+09+10+11+12+14+15+17 = 10+5+3+4+5+6+7+8 = 48
    model.add_table(
        {
            "df": df,
            "table_type": "FS_CASH_FLOW",
            "table_id": "tbl_cf_subtotal_no_code",
            "code_col": "Code",
            "amount_cols": ["CY"],
        }
    )
    return model


def test_t5_code_20_subtotal_row_without_code_excluded():
    """T5: Subtotal row (no code) between 12 and 14 is not included in Code 20 sum."""
    model = _build_cf_code20_subtotal_without_code()
    rule = CashFlowRules()
    materiality = MaterialityEngine()

    evidence = rule.evaluate_model(model, materiality=materiality)
    code_20 = next(e for e in evidence if "CF Formula Code 20 [CY]" in e.assertion_text)

    assert code_20.expected == 48.0
    assert code_20.actual == 48.0
    assert code_20.diff == 0.0


def _build_cf_code20_code13_subtotal_by_position() -> StatementModel:
    """T5 fixture: row with code 13 is subtotal by position (only 13 between 12 and 14); label not in builder list so code stays 13; rule excludes via _is_cf20_subtotal_row."""
    model = StatementModel("FS_CASH_FLOW")
    df = pd.DataFrame(
        {
            "Code": ["08", "09", "10", "11", "12", "13", "14", "15", "17", "20"],
            "Description": [
                "Depreciation",
                "Change receivables",
                "Other 10",
                "Other 11",
                "Other 12",
                "Other adjustments",
                "Interest paid",
                "Tax paid",
                "Other 17",
                "Net cash from operating activities",
            ],
            "CY": [10.0, 5.0, 3.0, 4.0, 5.0, 27.0, 6.0, 7.0, 8.0, 48.0],
        }
    )
    # 20 = 08+09+10+11+12+14+15+17 (13 excluded as subtotal by position) = 10+5+3+4+5+6+7+8 = 48
    model.add_table(
        {
            "df": df,
            "table_type": "FS_CASH_FLOW",
            "table_id": "tbl_cf_13_subtotal",
            "code_col": "Code",
            "amount_cols": ["CY"],
        }
    )
    return model


def test_t5_code_20_code_13_subtotal_excluded_by_position():
    """T5: Code 13 row that is subtotal (single 13 between 12 and 14) excluded from Code 20."""
    model = _build_cf_code20_code13_subtotal_by_position()
    rule = CashFlowRules()
    materiality = MaterialityEngine()

    evidence = rule.evaluate_model(model, materiality=materiality)
    code_20 = next(e for e in evidence if "CF Formula Code 20 [CY]" in e.assertion_text)

    assert code_20.expected == 48.0
    assert code_20.actual == 48.0
    assert code_20.diff == 0.0
