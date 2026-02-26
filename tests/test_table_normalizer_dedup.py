import pandas as pd

from quality_audit.utils.table_normalizer import TableNormalizer


def test_normalize_table_coalesces_duplicate_year_columns_by_filling_missing() -> None:
    """
    Characterization test (Phase 0):

    Current `TableNormalizer.normalize_table()` coalesces columns that share the same 4-digit year
    substring by selecting a primary and filling its missing values from duplicates, then dropping
    non-primary columns.
    """
    df = pd.DataFrame(
        {
            "Code": ["100", "200"],
            "31/12/2018 VND'000": [1000, None],
            "31/12/2018 VND'000.1": [None, 2000],
            "1/1/2018 VND'000": [500, 600],
        }
    )

    normalized_df, meta = TableNormalizer.normalize_table(df, heading="dummy")

    assert isinstance(meta, dict)
    # Phase 1 behavior groups by PERIOD KEY (full date when present). In this input:
    # - "31/12/2018 ..." and "31/12/2018 ... .1" are duplicates and are coalesced into one.
    # - "1/1/2018 ..." remains separate (different period key).
    cols = list(normalized_df.columns)
    assert "1/1/2018 VND'000" in cols
    assert "31/12/2018 VND'000" in cols or "31/12/2018 VND'000.1" in cols
    assert not ("31/12/2018 VND'000" in cols and "31/12/2018 VND'000.1" in cols)


def test_normalize_table_does_not_add_new_metadata_keys_yet() -> None:
    """
    Phase 1 expectation:

    Metadata contract is extended with dedup/flags fields per epic spec.
    """
    df = pd.DataFrame(
        {
            "Code": ["100"],
            "31/12/2018 VND'000": [1000],
            "31/12/2018 VND'000.1": [None],
        }
    )

    _normalized_df, meta = TableNormalizer.normalize_table(df, heading="dummy")
    # Minimum required keys (allow more in future).
    for k in [
        "detected_code_column",
        "detected_cur_col",
        "detected_prior_col",
        "header_row_idx",
        "normalized_columns",
        "dedup_period_columns_applied",
        "duplicated_period_groups",
        "dedup_conflicts",
        "suspicious_wide_table",
        "suspicious_wide_table_reasons",
    ]:
        assert k in meta
