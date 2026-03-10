import pandas as pd

from quality_audit.core.materiality import MaterialityEngine
from quality_audit.core.rules.netting_blocks import NettingBlocksRule


def test_netting_blocks_rule_emits_info_on_pass() -> None:
    df = pd.DataFrame(
        {
            "label": ["Total revenue", "Less: deductions", "Net revenue"],
            "2024": [1000, 200, 800],
        }
    )
    rule = NettingBlocksRule()
    materiality = MaterialityEngine()

    ev = rule.evaluate(
        df,
        materiality=materiality,
        table_type="GENERIC_NOTE",
        table_id="tbl_netting",
        amount_cols=["2024"],
        note_validation_mode="HIERARCHICAL_NETTING",
        note_validation_plan={
            "total_row_idx": 0,
            "less_row_idx": 1,
            "net_row_idx": 2,
            "amount_cols": ["2024"],
        },
    )

    assert ev, "Expected INFO evidence on pass to avoid unverified WARN"
    assert all(e.rule_id == "NETTING_BLOCKS" for e in ev)
    assert any(e.severity.name == "INFO" for e in ev)


def test_netting_blocks_rule_fails_when_net_mismatch() -> None:
    df = pd.DataFrame(
        {
            "label": ["Gross", "Less: discounts", "Net"],
            "2024": [1000, 200, 600],
        }
    )
    rule = NettingBlocksRule()
    materiality = MaterialityEngine()

    ev = rule.evaluate(
        df,
        materiality=materiality,
        table_type="GENERIC_NOTE",
        table_id="tbl_netting",
        amount_cols=["2024"],
        note_validation_mode="HIERARCHICAL_NETTING",
        note_validation_plan={
            "total_row_idx": 0,
            "less_row_idx": 1,
            "net_row_idx": 2,
            "amount_cols": ["2024"],
        },
    )

    assert any(e.severity.name != "INFO" for e in ev)
