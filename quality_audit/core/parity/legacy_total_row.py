"""
Legacy total-row helpers adapted from legacy/main.py.

This module intentionally preserves legacy-first behavior:
1) Prefer numeric row whose immediate previous row is fully blank.
2) If not found and strict=True => no total row (None).
3) If not found and strict=False => fallback to last numeric row.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Optional

import pandas as pd


def _normalize_numeric(value: object) -> float | None:
    if isinstance(value, str):
        value = value.replace(",", "").replace("(", "-").replace(")", "")
    parsed = pd.to_numeric(value, errors="coerce")
    if pd.isna(parsed):
        return None
    return float(parsed)


def _is_numeric_row(row: pd.Series) -> bool:
    return any(_normalize_numeric(v) is not None for v in row)


def _is_empty_row(row: pd.Series) -> bool:
    def _strip_text(x: object) -> str:
        s = str(x).strip()
        s = s.replace("-", "").replace("–", "").replace("—", "")
        s = s.replace("(", "").replace(")", "").replace(",", "")
        return s.strip()

    has_text = any(_strip_text(c) != "" for c in row)
    has_num = _is_numeric_row(row)
    return (not has_text) and (not has_num)


def find_legacy_total_row_index(
    df: pd.DataFrame,
    heading_lower: str = "",
    *,
    strict: bool = True,
) -> Optional[int]:
    """
    Ported from legacy/main.py::find_total_row_index with minimal adaptation.
    """
    if df is None or df.empty:
        return None

    heading_lower = str(heading_lower or "").lower()
    numeric_rows = [i for i in range(len(df)) if _is_numeric_row(df.iloc[i])]
    if not numeric_rows:
        return None

    for i in reversed(numeric_rows):
        # Adaptation note:
        # legacy/main.py effectively treated row 0 as having an implicit blank
        # predecessor. In current pipeline we require an actual preceding blank
        # row (i > 0) to avoid false total selection at row 0.
        if i <= 0:
            continue
        prev_empty = _is_empty_row(df.iloc[i - 1])
        if not prev_empty:
            continue

        if (
            "accrued expenses" in heading_lower
            or "deferred revenue" in heading_lower
            or "other payables" in heading_lower
            or "short-term provisions" in heading_lower
        ) and (numeric_rows[-1] - i >= 2):
            return numeric_rows[-1]

        if (
            "straight bonds and bonds convertible to a variable number of shares"
            in heading_lower
            or "convertible bonds" in heading_lower
            or "preference shares" in heading_lower
        ):
            j = i
            while j > 0:
                row_text = " ".join(str(x).lower() for x in df.iloc[j])
                if (
                    "within" not in row_text
                    and "after" not in row_text
                    and _is_numeric_row(df.iloc[j])
                ):
                    return j
                j -= 1

        if "acquisition of subsidiary" in heading_lower:
            j = i
            while j > 0:
                row_text = " ".join(str(x).lower() for x in df.iloc[j])
                if "net identifiable" in row_text:
                    return j
                j -= 1

        if "business segments" in heading_lower:
            row_text = " ".join(str(x).lower() for x in df.iloc[i])
            if "after tax" in row_text:
                j = i
                while j > 0:
                    row_text = " ".join(str(x).lower() for x in df.iloc[j])
                    if "segment revenue" in row_text:
                        return j
                    j -= 1
            else:
                return i

        return i

    if strict:
        return None
    return numeric_rows[-1]


@dataclass(frozen=True)
class LegacyTotalScope:
    total_row_idx: Optional[int]
    detail_rows: list[int]
    source: str


def resolve_legacy_note_total_scope(
    df: pd.DataFrame,
    heading_lower: str,
    table_type: str,
) -> LegacyTotalScope:
    """
    Priority used by current NOTE fallback path:
    1) Legacy blank-row-before-total (strict).
    2) TAX reconciliation fallback (legacy-compatible special case).
    3) No total row (never default to last row for generic notes).
    """
    n = len(df)
    total_idx = find_legacy_total_row_index(df, heading_lower, strict=True)
    if total_idx is not None:
        return LegacyTotalScope(
            total_row_idx=total_idx,
            detail_rows=list(range(0, total_idx)),
            source="legacy_blank_row_before_total",
        )

    if (
        table_type == "TAX_NOTE"
        and "reconciliation of effective tax rate" in heading_lower
        and n >= 3
    ):
        return LegacyTotalScope(
            total_row_idx=n - 1,
            detail_rows=list(range(1, n - 1)),
            source="legacy_tax_reconciliation_fallback",
        )

    return LegacyTotalScope(
        total_row_idx=None,
        detail_rows=[],
        source="legacy_no_total_detected",
    )


def resolve_note_total_scope_with_priority(
    df: pd.DataFrame,
    heading_lower: str,
    table_type: str,
    *,
    note_structure_scope: Optional[LegacyTotalScope] = None,
) -> LegacyTotalScope:
    """
    Canonical precedence used by audit_service:
    1) note_structure scope (when available and trusted)
    2) legacy blank-row-before-total fallback
    3) tax reconciliation fallback
    4) no-total
    """
    if (
        note_structure_scope is not None
        and note_structure_scope.total_row_idx is not None
        and note_structure_scope.detail_rows is not None
    ):
        return LegacyTotalScope(
            total_row_idx=note_structure_scope.total_row_idx,
            detail_rows=list(note_structure_scope.detail_rows),
            source="note_structure_scope_0",
        )
    return resolve_legacy_note_total_scope(df, heading_lower, table_type)
