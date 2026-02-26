import pandas as pd

from quality_audit.utils.table_normalizer import TableNormalizer


def test_detect_code_columns_with_suffixes() -> None:
    """
    Characterization test (Phase 0):

    `_detect_code_columns_with_synonyms()` should detect multiple code-like columns such as
    Code, Code.1, Code.2 (and other synonyms with numeric suffix).
    """
    df = pd.DataFrame(
        {
            "Code": ["100", "200"],
            "Code.1": ["A", "B"],
            "Description": ["Item 1", "Item 2"],
            "31/12/2018": [1, 2],
        }
    )

    code_cols = TableNormalizer._detect_code_columns_with_synonyms(df)
    # Current synonyms treat "Description" as code-like (used for exclusion from numeric sums).
    assert code_cols == ["Code", "Code.1", "Description"]


def test_detect_code_column_backward_compatible_returns_first_preferred() -> None:
    """
    Characterization test (Phase 0):

    `_detect_code_column_with_synonyms()` is a backward-compatible API returning a single column.
    When multiple code-like columns exist, it should prefer explicit code synonyms.
    """
    df = pd.DataFrame(
        {
            "Thuyết minh": ["1", "2"],
            "Code.1": ["A", "B"],
            "Code": ["100", "200"],
            "31/12/2018": [1, 2],
        }
    )

    code_col = TableNormalizer._detect_code_column_with_synonyms(df)
    assert code_col in {"Code", "Code.1"}
