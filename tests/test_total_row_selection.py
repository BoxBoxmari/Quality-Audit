import pandas as pd
import pytest

from quality_audit.config.feature_flags import FEATURE_FLAGS
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


def test_find_total_row_fallback_returns_legacy_last_numeric_row_in_parity_mode(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """
    Parity lock:
    In legacy parity mode + strict mode, when no explicit total row is detected,
    `_find_total_row()` must not guess by "last numeric row".
    """
    df = pd.DataFrame(
        {
            "A": ["Item 1", "Item 2", ""],
            "B": [100, 200, ""],
            "C": [10, 20, ""],
        }
    )

    v = _DummyValidator()
    monkeypatch.setattr(v, "_detect_total_rows", lambda df, **_: [])
    monkeypatch.setitem(FEATURE_FLAGS, "baseline_authoritative_default", False)
    monkeypatch.setitem(FEATURE_FLAGS, "legacy_parity_mode", True)
    monkeypatch.setitem(FEATURE_FLAGS, "tighten_total_row_keywords", True)
    idx = v._find_total_row(df, code_cols=[])
    assert idx is None


def test_find_total_row_heading_override_accrued_expenses_prefers_last_numeric_row(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """
    Legacy main.py parity lock:
    For accrued/deferred headings, when an empty-separator candidate is found far enough
    from the tail, total row should be forced to the last numeric row.
    """
    df = pd.DataFrame(
        {
            "A": ["Hdr", "Detail A", "", "Subtotal-like", "note", "Tail total-ish"],
            "B": ["", 10, "", 30, "x", 40],
        }
    )
    df.attrs["heading"] = "accrued expenses - short-term"

    v = _DummyValidator()
    monkeypatch.setattr(v, "_detect_total_rows", lambda df, **_: [])
    monkeypatch.setitem(FEATURE_FLAGS, "baseline_authoritative_default", False)
    monkeypatch.setitem(FEATURE_FLAGS, "legacy_parity_mode", True)
    monkeypatch.setitem(FEATURE_FLAGS, "tighten_total_row_keywords", True)

    idx = v._find_total_row(df, code_cols=[])
    assert idx == 5


def test_parity_mode_bypasses_safe_total_row_selection_fallbacks(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """
    Feature interaction lock:
    In parity mode (non-strict), safe_total_row_selection must not force None; fallback can return last numeric row.
    """
    df = pd.DataFrame(
        {
            "A": ["Detail 1", "Detail 2", "Detail 3"],
            "B": [1, 2, 3],
        }
    )
    v = _DummyValidator()
    monkeypatch.setattr(v, "_detect_total_rows", lambda df, **_: [])
    monkeypatch.setitem(FEATURE_FLAGS, "baseline_authoritative_default", False)
    monkeypatch.setitem(FEATURE_FLAGS, "legacy_parity_mode", True)
    monkeypatch.setitem(FEATURE_FLAGS, "tighten_total_row_keywords", False)
    monkeypatch.setitem(FEATURE_FLAGS, "safe_total_row_selection", True)

    idx = v._find_total_row(df, code_cols=[])
    assert idx == 2
