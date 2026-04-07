import pandas as pd

from quality_audit.core.parity.legacy_total_row import (
    LegacyTotalScope,
    find_legacy_total_row_index,
    resolve_legacy_note_total_scope,
    resolve_note_total_scope_with_priority,
)


def test_legacy_total_row_prefers_blank_row_separator() -> None:
    df = pd.DataFrame(
        {
            "Item": ["A", "B", "", "Total"],
            "CY": [10, 20, "", 30],
        }
    )
    assert find_legacy_total_row_index(df, "some heading", strict=True) == 3


def test_legacy_total_row_strict_does_not_force_last_row() -> None:
    df = pd.DataFrame(
        {
            "Item": ["A", "B", "Signature"],
            "CY": [10, 20, ""],
        }
    )
    assert find_legacy_total_row_index(df, "some heading", strict=True) is None


def test_legacy_total_row_non_strict_falls_back_last_numeric_row() -> None:
    df = pd.DataFrame(
        {
            "Item": ["A", "B", "C"],
            "CY": [10, 20, 25],
        }
    )
    assert find_legacy_total_row_index(df, "some heading", strict=False) == 2


def test_resolve_legacy_note_scope_tax_reconciliation_fallback() -> None:
    df = pd.DataFrame(
        {
            "Item": [
                "Accounting profit before tax",
                "Tax impact",
                "Effective tax rate",
            ],
            "CY": [100, -20, 80],
        }
    )
    scope = resolve_legacy_note_total_scope(
        df,
        "reconciliation of effective tax rate",
        "TAX_NOTE",
    )
    assert scope.total_row_idx == 2
    assert scope.detail_rows == [1]
    assert scope.source == "legacy_tax_reconciliation_fallback"


def test_priority_note_structure_then_legacy_then_none() -> None:
    """
    Priority lock:
    note_structure scope (when trusted) > legacy blank-row-before-total > no-total.
    """
    df = pd.DataFrame(
        {
            "Item": ["A", "B", "", "Total"],
            "CY": [10, 20, "", 30],
        }
    )
    structure_scope = LegacyTotalScope(total_row_idx=1, detail_rows=[0], source="x")
    resolved = resolve_note_total_scope_with_priority(
        df,
        "some note",
        "GENERIC_NOTE",
        note_structure_scope=structure_scope,
    )
    assert resolved.total_row_idx == 1
    assert resolved.detail_rows == [0]
    assert resolved.source == "note_structure_scope_0"

    resolved_legacy = resolve_note_total_scope_with_priority(
        df,
        "some note",
        "GENERIC_NOTE",
        note_structure_scope=None,
    )
    assert resolved_legacy.total_row_idx == 3
    assert resolved_legacy.detail_rows == [0, 1, 2]
    assert resolved_legacy.source == "legacy_blank_row_before_total"
