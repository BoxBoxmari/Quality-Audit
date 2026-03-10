"""
Shared table canonicalization for DOCX→DF→XLSX pipeline.

Reduces column explosion, removes index-row artifacts, merges Code.* duplicates,
and collapses header-explode while protecting semantic columns. Used by both
the Excel writer (FS casting) and validators for consistent shape.
"""

import logging
import re
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional, Tuple

import pandas as pd

logger = logging.getLogger(__name__)

# Code-like header base names (without .1, .2) for merge detection.
_CODE_BASE_NAMES = {"code", "no", "no.", "stt", "mã", "ma", "ref", "ref.", "num", "id"}
# Semantic columns to never drop on sparsity.
_SEMANTIC_HEADERS = {
    "note",
    "notes",
    "ref",
    "reference",
    "no.",
    "particulars",
    "description",
    "desc",
    "content",
    "nội dung",
    "thuyết minh",
    "chỉ tiêu",
    "mục",
}


@dataclass
class TableMeta:
    """Optional metadata for canonicalization (graceful defaults)."""

    table_id: Optional[str] = None
    table_no: Optional[int] = None
    docx_grid_cols: Optional[int] = None
    title: Optional[str] = None
    source: Optional[str] = None


@dataclass
class CanonReport:
    """Report from canonicalize_table for observability and conflict handling."""

    before_shape: Tuple[int, int]
    after_shape: Tuple[int, int]
    has_index_row: bool = False
    has_duplicate_headers: bool = False
    has_code_duplicates: bool = False
    header_explode: bool = False
    actions_taken: List[str] = field(default_factory=list)
    conflicts: List[Dict[str, Any]] = field(default_factory=list)
    confidence_scores: Optional[Dict[str, float]] = None


def _normalize_header_token(s: str) -> str:
    """Lowercase, collapse whitespace."""
    return " ".join(str(s).strip().lower().split())


def _is_index_row(values: List[Any]) -> bool:
    """True if row looks like 0, 1, 2, ... or integer column names."""
    if not values:
        return False
    try:
        nums = [int(float(str(v).strip())) for v in values if str(v).strip() != ""]
        if len(nums) < 2:
            return False
        return nums == list(range(len(nums))) or nums == list(range(1, len(nums) + 1))
    except (ValueError, TypeError):
        return False


def _columns_are_numeric_index(df: pd.DataFrame) -> bool:
    """True if df.columns are int or range-like (0,1,2,...)."""
    try:
        cols = list(df.columns)
        if len(cols) < 2:
            return False
        as_ints = [int(float(c)) for c in cols]
        return as_ints == list(range(len(as_ints)))
    except (ValueError, TypeError):
        return False


def _is_code_like_header(col: str) -> bool:
    """True if column is Code, Code.1, No., No.1, etc."""
    n = _normalize_header_token(col)
    if n in _CODE_BASE_NAMES:
        return True
    return bool(re.match(r"^(code|no\.?|stt|mã|ma|ref\.?|num|id)(\.\d+)?$", n))


def _code_base_name(col: str) -> str:
    """Return base name for grouping (e.g. 'Code.2' -> 'code')."""
    n = _normalize_header_token(col)
    m = re.match(r"^(code|no\.?|stt|mã|ma|ref\.?|num|id)(\.\d+)?$", n)
    if m:
        return m.group(1)
    return n


def _is_semantic_protected(col: str) -> bool:
    """True if column should not be dropped on sparsity."""
    n = _normalize_header_token(col)
    return any(n == h or n.startswith(h + " ") for h in _SEMANTIC_HEADERS)


def _detect_flags(df: pd.DataFrame, table_meta: Optional[TableMeta]) -> Dict[str, bool]:
    """Detect index-row, duplicate headers, code duplicates, header explode."""
    flags = {
        "has_index_row": False,
        "has_duplicate_headers": False,
        "has_code_duplicates": False,
        "header_explode": False,
    }
    if df.empty:
        return flags

    cols = [str(c).strip() for c in df.columns]
    # Index-row: columns are 0,1,2,... or first data row is 0,1,2,...
    if _columns_are_numeric_index(df):
        flags["has_index_row"] = True
    if len(df) > 0:
        first_row = df.iloc[0].tolist()
        if _is_index_row(first_row):
            flags["has_index_row"] = True

    # Duplicate headers: same name or name.1, name.2
    seen: Dict[str, int] = {}
    for c in cols:
        base = re.sub(r"\.\d+$", "", _normalize_header_token(c))
        seen[base] = seen.get(base, 0) + 1
    if any(v > 1 for v in seen.values()):
        flags["has_duplicate_headers"] = True

    # Code duplicates: multiple Code-like columns
    code_like = [c for c in cols if _is_code_like_header(c)]
    if len(code_like) > 1:
        flags["has_code_duplicates"] = True

    # Header explode: cols >> docx_grid_cols (e.g. 1.5x)
    expected = (
        table_meta.docx_grid_cols if table_meta and table_meta.docx_grid_cols else None
    )
    if (
        expected is not None
        and len(cols) >= int(1.5 * expected)
        or expected is None
        and len(code_like) >= 2
        and len(cols) >= 12
    ):
        flags["header_explode"] = True

    return flags


def _fix_index_row(df: pd.DataFrame, report: CanonReport) -> pd.DataFrame:
    """Ensure columns are strings; drop first row if it is 0,1,2,...; no silent drop of real data."""
    out = df.copy()
    out.columns = [str(c) for c in out.columns]

    if out.empty or len(out) < 2:
        return out

    first_row_vals = out.iloc[0].tolist()
    if _columns_are_numeric_index(df):
        report.actions_taken.append("columns_renamed_from_numeric_index")
        out.columns = [f"Col_{i}" for i in range(len(out.columns))]
    if _is_index_row(first_row_vals):
        report.actions_taken.append("dropped_first_row_index_artifact")
        out = out.iloc[1:].reset_index(drop=True)
    return out


def _merge_code_columns(df: pd.DataFrame, report: CanonReport) -> pd.DataFrame:
    """Merge Code, Code.1, Code.2,... first-non-null; record conflicts when both non-null and different."""
    cols = list(df.columns)
    code_groups: Dict[str, List[str]] = {}
    for c in cols:
        base = _code_base_name(c)
        if _is_code_like_header(c):
            code_groups.setdefault(base, []).append(c)

    if not code_groups:
        return df

    out = df.copy()
    drop_cols: List[str] = []

    for base, group in code_groups.items():
        if len(group) <= 1:
            continue
        report.has_code_duplicates = True
        report.actions_taken.append(f"merge_code_group_{base}_{len(group)}_cols")

        # Prefer column without suffix, then .1, .2 order
        def order_key(name: str) -> Tuple[int, str]:
            n = _normalize_header_token(name)
            m = re.search(r"\.(\d+)$", n)
            return (int(m.group(1)) if m else 0, name)

        ordered = sorted(group, key=order_key)
        target = ordered[0]
        for c in ordered[1:]:
            # Merge: first non-null wins per row; if both non-null and different, conflict
            merged = out[target].copy()
            for idx in out.index:
                a, b = out.loc[idx, target], out.loc[idx, c]
                sa, sb = (
                    str(a).strip() if pd.notna(a) else "",
                    (str(b).strip() if pd.notna(b) else ""),
                )
                if sa and sb and sa != sb:
                    report.conflicts.append(
                        {
                            "type": "code_merge_conflict",
                            "columns": [target, c],
                            "row": int(idx),
                            "values": [sa, sb],
                        }
                    )
                    merged.loc[idx] = sa  # keep left
                elif sb and not sa:
                    merged.loc[idx] = b
            out[target] = merged
            drop_cols.append(c)

    if drop_cols:
        out = out.drop(
            columns=[c for c in drop_cols if c in out.columns], errors="ignore"
        )
    return out


def _collapse_duplicate_headers(
    df: pd.DataFrame, table_meta: Optional[TableMeta], report: CanonReport
) -> pd.DataFrame:
    """Collapse columns that are duplicate (same normalized header + row-wise equal). Protect multi-year and semantic."""
    if not report.header_explode:
        return df
    cols = list(df.columns)
    if len(cols) < 2:
        return df

    # Build normalized header -> list of column names
    norm_to_cols: Dict[str, List[str]] = {}
    for c in cols:
        n = _normalize_header_token(c)
        if _is_semantic_protected(c):
            norm_to_cols.setdefault(n, []).append(c)
            continue
        # Skip year-like headers (protect multi-year)
        if re.search(r"20\d{2}|19\d{2}", n):
            norm_to_cols.setdefault(n, []).append(c)
            continue
        norm_to_cols.setdefault(n, []).append(c)

    # Collapse only when: same norm name, multiple cols, and row-wise identical (or one non-null)
    out = df.copy()
    to_drop: List[str] = []
    for _norm, group in norm_to_cols.items():
        if len(group) <= 1:
            continue
        # Check row-wise equality for collapse
        keep = group[0]
        for c in group[1:]:
            diff = (
                out[keep].astype(str).fillna("") != out[c].astype(str).fillna("")
            ).any()
            if diff.any():
                report.conflicts.append(
                    {
                        "type": "header_collapse_conflict",
                        "columns": [keep, c],
                        "reason": "row_values_differ",
                    }
                )
                continue
            to_drop.append(c)
            report.actions_taken.append(f"collapse_duplicate_header_{c}_into_{keep}")

    if to_drop:
        out = out.drop(
            columns=[c for c in to_drop if c in out.columns], errors="ignore"
        )
    return out


def canonicalize_table(
    df: pd.DataFrame,
    table_meta: Optional[TableMeta] = None,
) -> Tuple[pd.DataFrame, CanonReport]:
    """
    Canonicalize table to reduce column explosion, remove index-row, merge Code.*.

    Args:
        df: Input DataFrame (may have index-row, Code.1/Code.2, exploded headers).
        table_meta: Optional metadata (docx_grid_cols for explode detection).

    Returns:
        (df_canon, canon_report) for observability and conflict handling.
    """
    before = (len(df), len(df.columns) if not df.empty else 0)
    report = CanonReport(
        before_shape=before,
        after_shape=before,
        conflicts=[],
        actions_taken=[],
    )

    if df.empty:
        return df, report

    flags = _detect_flags(df, table_meta)
    report.has_index_row = flags["has_index_row"]
    report.has_duplicate_headers = flags["has_duplicate_headers"]
    report.has_code_duplicates = flags["has_code_duplicates"]
    report.header_explode = flags["header_explode"]

    out = df.copy()
    out = _fix_index_row(out, report)
    out = _merge_code_columns(out, report)
    out = _collapse_duplicate_headers(out, table_meta, report)

    report.after_shape = (len(out), len(out.columns))
    if report.conflicts:
        logger.debug(
            "canonicalize_table conflicts table_id=%s before=%s after=%s conflicts=%s",
            table_meta.table_id if table_meta else None,
            report.before_shape,
            report.after_shape,
            len(report.conflicts),
        )
    return out, report
