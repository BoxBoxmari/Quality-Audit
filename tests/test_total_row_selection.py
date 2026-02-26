import pandas as pd

from quality_audit.core.validators.base_validator import BaseValidator


class _DummyValidator(BaseValidator):
    def validate(
        self, df: pd.DataFrame, heading: str | None = None
    ):  # pragma: no cover
        raise NotImplementedError()


def test_find_total_row_prefers_detected_total_rows_when_present() -> None:
    """
    Characterization test (Phase 0):

    Current `_find_total_row()` uses `_detect_total_rows()` (RowClassifier-based) first and returns
    the last detected total row.
    """
    df = pd.DataFrame(
        {
            "A": ["Item 1", "Item 2", "Grand Total"],
            "B": [100, 200, 300],
            "C": [10, 20, 30],
        }
    )

    v = _DummyValidator()
    idx = v._find_total_row(df, code_cols=[])
    assert idx == 2


def test_find_total_row_fallback_returns_last_numeric_row_when_no_detected_totals() -> (
    None
):
    """
    Characterization test (Phase 0):

    When RowClassifier doesn't yield totals, fallback returns the last numeric row (after blank-row
    heuristic scan).
    """
    df = pd.DataFrame(
        {
            "A": ["Item 1", "Item 2", ""],
            "B": [100, 200, ""],
            "C": [10, 20, ""],
        }
    )

    v = _DummyValidator()
    idx = v._find_total_row(df, code_cols=[])
    # Phase 2 (A1 safe_total_row_selection): no explicit total keywords -> return None (safe).
    assert idx is None
