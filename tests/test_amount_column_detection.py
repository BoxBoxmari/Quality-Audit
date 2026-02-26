import pandas as pd

from quality_audit.utils.column_detector import ColumnDetector


def test_detect_financial_columns_advanced_two_period_columns() -> None:
    """
    Characterization test (Phase 0):

    A2 will later restrict sums to amount columns; current behavior relies on ColumnDetector.
    This test locks basic period-column detection on typical headers.
    """
    df = pd.DataFrame(
        {
            "Code": ["100"],
            "31/12/2018 VND'000": [1],
            "1/1/2018 VND'000": [2],
        }
    )

    cur, prior = ColumnDetector.detect_financial_columns_advanced(df)
    # Do not assert exact mapping of cur/prior (depends on heuristics); just assert both detected.
    assert cur in df.columns
    assert prior in df.columns


def test_detect_financial_columns_advanced_multi_period_table_returns_two_columns() -> (
    None
):
    """
    Characterization test (Phase 0):

    For multi-period tables, ColumnDetector still returns a (cur, prior) pair; A2 will later expand
    scope to a contiguous block when >2 period-like headers are present.
    """
    df = pd.DataFrame(
        {
            "Code": ["100"],
            "31/12/2018": [1],
            "31/12/2017": [2],
            "31/12/2016": [3],
        }
    )

    cur, prior = ColumnDetector.detect_financial_columns_advanced(df)
    assert cur in df.columns
    assert prior in df.columns
