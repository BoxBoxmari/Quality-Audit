import pandas as pd

from quality_audit.core.evidence import Severity
from quality_audit.core.rules.basic_numeric_checks import BasicNumericChecksRule


class _FakeMateriality:
    """Minimal stub exposing get_tolerance for BasicNumericChecksRule."""

    def __init__(self, tol: float = 1.0) -> None:
        self._tol = tol

    def get_tolerance(self) -> float:
        return self._tol


def test_vertical_sum_label_regex_can_produce_minor_fail():
    """
    Phase 3: When a label-driven total is present, B1 may emit a MINOR FAIL.
    """
    df = pd.DataFrame(
        {
            "Label": ["Line 1", "Line 2", "Total"],
            "Amount": [100.0, 200.0, 350.0],
        }
    )
    rule = BasicNumericChecksRule()
    materiality = _FakeMateriality(tol=1.0)

    evidence = rule._check_vertical_sum(  # type: ignore[attr-defined]
        df=df,
        amount_cols=["Amount"],
        label_col="Label",
        materiality=materiality,
        table_type="NOTE_BREAKDOWN",
        table_id="B1_LABEL",
        low_confidence=False,
    )

    assert evidence, "Expected at least one B1 evidence for label-driven total"
    ev = evidence[0]
    assert ev.metadata.get("total_detection_strategy") == "label_regex"
    # diff is intentionally above tolerance so this remains a MINOR fail.
    assert ev.is_material is True
    assert ev.severity == Severity.MINOR


def test_vertical_sum_heuristic_totals_only_emit_info():
    """
    Phase 3: Heuristic totals (last_numeric / last_row) must only emit INFO
    diagnostics without driving FAILs.
    """
    df = pd.DataFrame(
        {
            "Label": ["Line 1", "Line 2", "Line 3"],
            "Amount": [100.0, 200.0, 350.0],
        }
    )
    rule = BasicNumericChecksRule()
    materiality = _FakeMateriality(tol=1.0)

    evidence = rule._check_vertical_sum(  # type: ignore[attr-defined]
        df=df,
        amount_cols=["Amount"],
        label_col="Label",
        materiality=materiality,
        table_type="NOTE_BREAKDOWN",
        table_id="B1_HEURISTIC",
        low_confidence=False,
    )

    assert evidence, "Expected B1 evidence even for heuristic totals"
    ev = evidence[0]
    # With no TOTAL-like label, detection must fall back to heuristics.
    assert ev.metadata.get("total_detection_strategy") in {"last_numeric", "last_row"}
    # Heuristic totals are downgraded to INFO-only diagnostics.
    assert ev.is_material is False
    assert ev.severity == Severity.INFO
