"""
FS anchor index: index of financial statement line items for note tie-out and validation.

Used in Phase 2 to infer note_ref for note tables and to support NOTE_TIE_OUT rules.
"""

from __future__ import annotations

import re
from typing import Any

import pandas as pd

FS_TABLE_TYPES = (
    "FS_INCOME_STATEMENT",
    "FS_BALANCE_SHEET",
    "FS_CASH_FLOW",
    "FS_EQUITY",
)


def _normalize_label(text: str) -> str:
    """Normalize label for matching: lower, strip, collapse spaces."""
    if not text or not isinstance(text, str):
        return ""
    return " ".join(str(text).lower().strip().split())


def _normalize_note_ref(text: Any) -> str:
    """Normalize note reference: extract digits from 'Note 4', '4', 'Thuyết minh số 4'."""
    if text is None or (isinstance(text, float) and pd.isna(text)):
        return ""
    s = str(text).strip()
    if not s:
        return ""
    # "Note 4" / "Thuyết minh số 4" -> "4"
    m = re.search(r"\d+", s)
    if not m:
        return s
    digits = m.group(0)
    # Preserve legacy semantic matching by canonicalizing 04/004 -> 4.
    return str(int(digits)) if digits.isdigit() else digits


def _parse_amount(val: Any) -> float:
    """Parse cell value to float; handle parentheses and commas."""
    if pd.isna(val) or val is None:
        return 0.0
    if isinstance(val, (int, float)):
        return float(val)
    s = str(val).strip()
    is_negative = False
    if s.startswith("(") and s.endswith(")"):
        is_negative = True
        s = s[1:-1].strip()
    elif s.startswith("-"):
        is_negative = True
        s = s[1:].strip()
    s = s.replace(",", "").replace(" ", "")
    try:
        v = float(s)
        return -v if is_negative else v
    except ValueError:
        return 0.0


# Unit hint constants for tie-out scaling (Pha 2.3)
UNIT_HINT_VND = "VND"
UNIT_HINT_VND_000 = "VND_000"

# Patterns: VND'000 / VND (000) / triệu đồng / Unit: VND'000 / Đơn vị: VND'000
_RE_VND_000 = re.compile(
    r"vnd\s*['\u2019]?\s*000|vnd\s*\(\s*000\s*\)|tri[eệ]u\s*đồng|"
    r"unit\s*:\s*vnd\s*['\u2019]?000|đơn\s*vị\s*:\s*vnd\s*['\u2019]?000",
    re.IGNORECASE,
)
# VND (plain) / Unit: VND / Đơn vị: VND / đồng
_RE_VND = re.compile(
    r"\bvnd\b|unit\s*:\s*vnd\b|đơn\s*vị\s*:\s*vnd\b|đồng\s*$",
    re.IGNORECASE,
)


def infer_unit_hint_for_table(t_info: dict[str, Any]) -> str:
    """
    Infer unit from table heading and header row for tie-out scaling (Pha 2.3).

    Returns UNIT_HINT_VND_000 ("VND_000"), UNIT_HINT_VND ("VND"), or "" if unclear.
    """
    heading = (t_info.get("heading") or "").strip()
    df = t_info.get("df")
    parts: list[str] = [heading]
    if df is not None and not df.empty:
        parts.extend(str(c).strip() for c in df.columns)
        if len(df) > 0:
            parts.extend(str(x).strip() for x in df.iloc[0].tolist())
    text = " ".join(parts).lower()
    if _RE_VND_000.search(text):
        return UNIT_HINT_VND_000
    if _RE_VND.search(text):
        return UNIT_HINT_VND
    return ""


def _detect_label_and_note_cols(
    df: pd.DataFrame, code_col: str, amount_cols: list[str]
) -> tuple[str | None, str | None]:
    """Detect label and note column names (same heuristic as StatementModel)."""
    label_col = None
    note_col = None
    for col in df.columns:
        if col == code_col or col in amount_cols:
            continue
        col_str = str(col).lower()
        if not note_col and (
            "note" in col_str or "thuyết minh" in col_str or col_str == "tm"
        ):
            note_col = col
        elif not label_col:
            label_col = col
    return label_col, note_col


def build_fs_anchor_index(tables_info: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """
    Build an index of FS line items from classified tables for note tie-out and lookup.

    Each entry has: statement_type, code, label_norm, note_ref_norm,
    amounts_by_period (dict col_name -> float), unit_hint (optional).

    Only tables with table_type in FS_TABLE_TYPES are included.
    """
    anchors: list[dict[str, Any]] = []
    for t_info in tables_info:
        table_type = t_info.get("table_type") or ""
        if table_type not in FS_TABLE_TYPES:
            continue
        df = t_info.get("df")
        if df is None or df.empty:
            continue
        code_col = t_info.get("code_col")
        amount_cols = t_info.get("amount_cols") or []
        if not code_col or not amount_cols:
            continue
        label_col, note_col = _detect_label_and_note_cols(df, code_col, amount_cols)
        context = t_info.get("context") or {}
        unit_hint = context.get("unit_hint")  # Pha 2.3 will set this

        for _idx, row in df.iterrows():
            code = str(row[code_col]).strip() if pd.notna(row.get(code_col)) else ""
            if not code and note_col and pd.notna(row.get(note_col)):
                note_val = str(row[note_col]).strip()
                if note_val.isdigit() and 1 <= len(note_val) <= 2:
                    code = note_val
            if not code:
                continue
            if code.endswith(".0"):
                code = code[:-2]
            if code.isdigit() and len(code) == 1:
                code = f"0{code}"

            label = (
                str(row[label_col]).strip()
                if label_col and pd.notna(row.get(label_col))
                else ""
            )
            note_ref_raw = row.get(note_col) if note_col else None
            note_ref_norm = _normalize_note_ref(note_ref_raw)

            amounts_by_period: dict[str, float] = {}
            for col in amount_cols:
                amounts_by_period[col] = _parse_amount(row.get(col))

            anchors.append(
                {
                    "statement_type": table_type,
                    "code": code,
                    "label_norm": _normalize_label(label),
                    "note_ref_norm": note_ref_norm,
                    "amounts_by_period": amounts_by_period,
                    "unit_hint": unit_hint,
                    "table_id": t_info.get("table_id", ""),
                }
            )
    return anchors


# Patterns to extract note number from heading (e.g. "Note 4", "Thuyết minh số 4")
_NOTE_HEADING_PATTERNS = [
    re.compile(r"note\s+(\d+)", re.IGNORECASE),
    re.compile(r"thuyết minh\s*số\s*(\d+)", re.IGNORECASE),
    re.compile(r"thuyet minh\s*so\s*(\d+)", re.IGNORECASE),
    # Legacy shorthand appears in headings like "TM 09", "TM.9", "tm số 04"
    re.compile(r"\btm\.?\s*(?:số|so)?\s*(\d+)\b", re.IGNORECASE),
]


def infer_note_ref_for_table(
    t_info: dict[str, Any],
    fs_anchor_index: list[dict[str, Any]] | None = None,
) -> str:
    """
    Infer note_ref for a note table (GENERIC_NOTE / TAX_NOTE).

    Priority: (1) t_info["context"]["note_number"], (2) parse from t_info["heading"].
    Returns normalized note ref (e.g. "4") or "".
    fs_anchor_index is reserved for optional validation; not required for inference.
    """
    context = t_info.get("context") or {}
    note_number = context.get("note_number")
    if note_number is not None and str(note_number).strip():
        return _normalize_note_ref(note_number)
    heading = t_info.get("heading") or ""
    if not heading:
        return ""
    heading_str = str(heading).strip()
    for pat in _NOTE_HEADING_PATTERNS:
        m = pat.search(heading_str)
        if m:
            return _normalize_note_ref(m.group(1))
    return ""


def index_by_note_ref(
    anchors: list[dict[str, Any]],
) -> dict[str, list[dict[str, Any]]]:
    """Group anchors by note_ref_norm for lookup from note tables."""
    by_note: dict[str, list[dict[str, Any]]] = {}
    for a in anchors:
        ref = a.get("note_ref_norm") or ""
        if ref not in by_note:
            by_note[ref] = []
        by_note[ref].append(a)
    return by_note


def index_by_label_norm(
    anchors: list[dict[str, Any]],
) -> dict[str, list[dict[str, Any]]]:
    """Index anchors by normalized label for fuzzy match from note headings."""
    by_label: dict[str, list[dict[str, Any]]] = {}
    for a in anchors:
        label = a.get("label_norm") or ""
        if not label:
            continue
        if label not in by_label:
            by_label[label] = []
        by_label[label].append(a)
    return by_label
