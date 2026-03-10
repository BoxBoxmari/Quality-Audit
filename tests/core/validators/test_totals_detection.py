"""Tests for _find_total_row: Rule B (blank label), Rule C (sum equation), metadata on context."""

import pandas as pd

from quality_audit.core.validators.base_validator import BaseValidator


class _DummyValidator(BaseValidator):
    def validate(
        self, df: pd.DataFrame, heading: str | None = None
    ):  # pragma: no cover
        raise NotImplementedError()


class _ContextCapture:
    """Minimal context that captures set_last_total_row_metadata calls."""

    def __init__(self):
        self.last_total_row_metadata = None

    def set_last_total_row_metadata(self, metadata):
        self.last_total_row_metadata = metadata


def test_find_total_row_rule_b_blank_label() -> None:
    """Rule B: row with blank label cells but numeric in amount cols is selected."""
    # Use "Item" (TEXT) + "CY 2024" (NUMERIC_CY) so only last row has blank label
    df = pd.DataFrame(
        {
            "Item": ["Item 1", "Item 2", ""],
            "CY 2024": [100, 200, 300],
        }
    )
    v = _DummyValidator()
    v.context = _ContextCapture()
    idx = v._find_total_row(df, code_cols=[])
    assert idx == 2
    assert v.context.last_total_row_metadata is not None
    assert v.context.last_total_row_metadata.get("method") == "rule_b_blank_label"
    assert v.context.last_total_row_metadata.get("totals_candidates_found") == 1


def test_find_total_row_keyword_guardrail_rejects_early_fake_total() -> None:
    """R3: First row labelled 'Total' with a value is rejected when >3 numeric rows below (top half)."""
    # Row 0 = fake total (many numeric below); row 4 = real total. Guardrail must pick row 4.
    df = pd.DataFrame(
        {
            "Item": ["Total", "A", "B", "C", "Total"],
            "CY 2024": [999.0, 100.0, 200.0, 300.0, 600.0],
        }
    )
    v = _DummyValidator()
    v.context = _ContextCapture()
    idx = v._find_total_row(df, code_cols=[])
    assert idx == 4
    assert v.context.last_total_row_metadata is not None
    # May be keyword_total_row or row_classifier; both correctly select last total row
    assert v.context.last_total_row_metadata.get("method") in (
        "keyword_total_row",
        "row_classifier",
    )
