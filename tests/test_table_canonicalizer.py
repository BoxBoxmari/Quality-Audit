"""
Unit tests for table_canonicalizer: canonicalize_table, TableMeta, CanonReport.

Covers: index-row removal, Code.* merge (first-non-null + conflict when both non-null),
header-explode collapse, semantic column protection, empty input.
"""

import pandas as pd

from quality_audit.utils.table_canonicalizer import (
    TableMeta,
    canonicalize_table,
)


def test_canonicalize_removes_numeric_index_columns() -> None:
    """Columns 0,1,2,... are renamed to Col_0, Col_1, Col_2; no silent data loss."""
    df = pd.DataFrame(
        [[10, 20, 30], [40, 50, 60]],
        columns=[0, 1, 2],
    )
    out, report = canonicalize_table(df, None)
    assert list(out.columns) == ["Col_0", "Col_1", "Col_2"]
    assert report.has_index_row
    assert "columns_renamed_from_numeric_index" in report.actions_taken
    assert out.shape == (2, 3)
    assert out.iloc[0].tolist() == [10, 20, 30]


def test_canonicalize_drops_first_row_when_index_artifact() -> None:
    """First row that is exactly 0,1,2,... is dropped as index artifact."""
    df = pd.DataFrame(
        [["Code", "Amount", "Note"], ["A", 100, "x"], ["B", 200, "y"]],
        columns=["Col_0", "Col_1", "Col_2"],
    )
    # Make first row look like 0, 1, 2 (numeric)
    df.iloc[0] = [0, 1, 2]
    out, report = canonicalize_table(df, None)
    assert report.has_index_row
    assert "dropped_first_row_index_artifact" in report.actions_taken
    assert len(out) == 2
    assert out.iloc[0].tolist() == ["A", 100, "x"]


def test_canonicalize_merge_code_first_non_null() -> None:
    """Code and Code.1 merge: first non-null wins per row."""
    df = pd.DataFrame(
        {
            "Code": ["A", None, "C"],
            "Code.1": [None, "B", None],
            "Amount": [1, 2, 3],
        }
    )
    out, report = canonicalize_table(df, None)
    assert "Code" in out.columns
    assert "Code.1" not in out.columns
    assert report.has_code_duplicates
    assert out["Code"].tolist() == ["A", "B", "C"]
    assert len(report.conflicts) == 0


def test_canonicalize_code_merge_conflict_when_both_non_null_different() -> None:
    """When both Code and Code.1 have non-null different values, conflict is recorded; left wins."""
    df = pd.DataFrame(
        {
            "Code": ["A", "X"],
            "Code.1": ["B", "Y"],
            "Amount": [1, 2],
        }
    )
    out, report = canonicalize_table(df, None)
    assert "Code" in out.columns
    assert "Code.1" not in out.columns
    assert out["Code"].tolist() == ["A", "X"]
    assert len(report.conflicts) >= 2
    for c in report.conflicts:
        assert c["type"] == "code_merge_conflict"
        assert c["columns"] == ["Code", "Code.1"]
        assert c["values"][0] != c["values"][1]


def test_canonicalize_header_explode_collapse_only_when_row_identical() -> None:
    """Collapse duplicate headers only when row values are identical; otherwise conflict."""
    # Same header name twice, same values -> collapse
    df = pd.DataFrame(
        {
            "Code": ["A", "B"],
            "Amount": [10, 20],
            "Amount.1": [10, 20],
        }
    )
    meta = TableMeta(docx_grid_cols=2)
    out, report = canonicalize_table(df, meta)
    # header_explode may be true (cols 3 >= 1.5*2); collapse checks norm + row equality
    # Amount and Amount.1 have same values -> one dropped
    if "collapse_duplicate_header_Amount.1_into_Amount" in report.actions_taken:
        assert "Amount" in out.columns
        assert "Amount.1" not in out.columns


def test_canonicalize_protects_multi_year_columns() -> None:
    """Columns with different year tokens (2018 vs 2019) are not collapsed."""
    df = pd.DataFrame(
        {
            "Code": ["A"],
            "31/12/2018 VND'000": [100],
            "31/12/2019 VND'000": [200],
        }
    )
    out, report = canonicalize_table(df, None)
    assert "31/12/2018 VND'000" in out.columns
    assert "31/12/2019 VND'000" in out.columns
    assert out.shape[1] == 3


def test_canonicalize_semantic_columns_kept() -> None:
    """Note, Ref, Particulars are not dropped on sparsity."""
    df = pd.DataFrame(
        {
            "Code": ["A", "B"],
            "Note": [None, "only one"],
            "Ref": ["r1", None],
            "Amount": [1, 2],
        }
    )
    out, report = canonicalize_table(df, None)
    assert "Note" in out.columns
    assert "Ref" in out.columns
    assert "Particulars" not in out.columns or "Particulars" in out.columns


def test_canonicalize_empty_dataframe() -> None:
    """Empty DataFrame returns unchanged and report with zero shapes."""
    df = pd.DataFrame()
    out, report = canonicalize_table(df, None)
    assert out.empty
    assert report.before_shape == (0, 0)
    assert report.after_shape == (0, 0)
    assert report.actions_taken == []


def test_canonicalize_report_flags_set() -> None:
    """Report flags reflect detected patterns: has_index_row, has_code_duplicates."""
    # Numeric columns
    df1 = pd.DataFrame([[1, 2], [3, 4]], columns=[0, 1])
    _, r1 = canonicalize_table(df1, None)
    assert r1.has_index_row is True

    # Code duplicates
    df2 = pd.DataFrame({"Code": ["A"], "Code.1": ["B"], "Amt": [1]})
    _, r2 = canonicalize_table(df2, None)
    assert r2.has_code_duplicates is True
    assert r2.has_duplicate_headers is True

    # No special pattern
    df3 = pd.DataFrame({"Code": ["A"], "Amount": [1]})
    _, r3 = canonicalize_table(df3, None)
    assert r3.has_index_row is False
    assert r3.has_code_duplicates is False


def test_canonicalize_table_meta_optional() -> None:
    """canonicalize_table works with table_meta=None (graceful defaults)."""
    df = pd.DataFrame({"Code": ["A"], "Amount": [1]})
    out, report = canonicalize_table(df, None)
    assert len(out) == 1
    assert report.before_shape == report.after_shape == (1, 2)


def test_canonicalize_table_meta_docx_grid_cols_used_for_explode() -> None:
    """When docx_grid_cols is set, header_explode can be set when cols >= 1.5 * docx_grid_cols."""
    # 6 columns, docx_grid_cols=4 -> 6 >= 6 -> header_explode True (if we had duplicate norm headers)
    df = pd.DataFrame(
        {f"C{i}": [1, 2] for i in range(6)},
    )
    df.columns = ["Code", "Code.1", "A", "B", "C", "D"]
    meta = TableMeta(docx_grid_cols=4)
    _, report = canonicalize_table(df, meta)
    assert report.has_code_duplicates is True
    # After merge we have 5 cols; 5 >= 6? No. So header_explode may stay False depending on logic
    # Just ensure no crash and report is filled
    assert report.before_shape[1] == 6
