import pandas as pd

from quality_audit.utils.numeric_utils import normalize_numeric_column


def test_normalize_numeric_column_parentheses_negative_baseline() -> None:
    # Current baseline: parentheses are converted to a leading '-' via string replace.
    assert normalize_numeric_column("(123)") == -123


def test_normalize_numeric_column_nbsp_currently_coerces_to_nan() -> None:
    # Phase 1: robust parsing normalizes NBSP as thousands separator.
    val = normalize_numeric_column("1\u00a0234")
    assert val == 1234


def test_normalize_numeric_column_em_dash_currently_coerces_to_nan() -> None:
    # Characterization: em-dash variants are not handled yet, expect NaN.
    assert pd.isna(normalize_numeric_column("–"))
    assert pd.isna(normalize_numeric_column("—"))
