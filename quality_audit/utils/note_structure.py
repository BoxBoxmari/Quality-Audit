"""
NOTE Structure Engine — row/segment/scope analysis for NOTE tables.

Provides analyze_note_table() as the single source for label_col, amount_cols,
row types, segments (OB/CB/movement per segment), and scopes for vertical sum.
Used by audit_service for NOTE path; rules consume segments/scopes via table_info.
"""

from __future__ import annotations

import re
import unicodedata
from dataclasses import dataclass, field
from enum import Enum
from typing import Any

import pandas as pd

# Minimum fraction of non-null numeric cells in a column to be treated as amount column
NUMERIC_DENSITY_THRESHOLD = 0.15
# Minimum fraction of non-empty text in a column to be treated as label column
TEXT_DENSITY_THRESHOLD = 0.3
# Minimum confidence (0–1) for segment to be used for movement validation
SEGMENT_CONFIDENCE_THRESHOLD = 0.5


class RowType(str, Enum):
    """Row classification for NOTE tables."""

    OPENING = "OPENING"
    CLOSING = "CLOSING"
    TOTAL_LIKE = "TOTAL_LIKE"
    SECTION_HEADER = "SECTION_HEADER"
    MOVEMENT = "MOVEMENT"
    BLANK = "BLANK"
    OTHER = "OTHER"


class NoteMode(str, Enum):
    """High-level semantic mode for NOTE tables.

    Phase 1: We introduce the enum and plumb it through NoteStructureResult
    without changing routing logic yet. Later phases will derive a richer
    mode from structure + heading semantics.
    """

    FS_PRIMARY = "FS_PRIMARY"
    MOVEMENT_ROLLFORWARD = "MOVEMENT_ROLLFORWARD"
    SCOPED_TOTAL = "SCOPED_TOTAL"
    HIERARCHICAL_SUBTOTALS = "HIERARCHICAL_SUBTOTALS"
    LISTING_NO_TOTAL = "LISTING_NO_TOTAL"
    SINGLE_ROW_DISCLOSURE = "SINGLE_ROW_DISCLOSURE"
    NO_TOTAL_DECLARED = "NO_TOTAL_DECLARED"
    UNDETERMINED = "UNDETERMINED"


class NoteValidationMode(str, Enum):
    """Planner output for how NOTE rules should treat this table.

    This is intentionally coarser than NoteMode and designed for routing/
    gating rules (movement-by-rows vs generic numeric vs listing/NO_TOTAL vs
    undetermined).  It is kept separate from NoteMode for backward
    compatibility with existing callers.
    """

    MOVEMENT_BY_ROWS = "MOVEMENT_BY_ROWS"
    MOVEMENT_BY_COLUMNS = "MOVEMENT_BY_COLUMNS"
    HIERARCHICAL_NETTING = "HIERARCHICAL_NETTING"
    GENERIC_NUMERIC_NOTE = "GENERIC_NUMERIC_NOTE"
    LISTING_NO_TOTAL = "LISTING_NO_TOTAL"
    LISTING_TOTALS = "LISTING_TOTALS"
    UNDETERMINED = "UNDETERMINED"


class StructureStatus(str, Enum):
    """Coarse structural status used for routing / diagnostics."""

    STRUCTURE_OK = "STRUCTURE_OK"
    STRUCTURE_NO_TOTAL = "STRUCTURE_NO_TOTAL"
    STRUCTURE_LISTING = "STRUCTURE_LISTING"
    STRUCTURE_UNDETERMINED = "STRUCTURE_UNDETERMINED"


# EN/VN patterns for row classification (aligned with structural_fingerprint semantics)
_OPENING_RE = re.compile(
    r"(?i)\b(opening|số\s*dư?\s*đầu|đầu\s*(năm|kỳ)|beginning|balance\s*b/?f|beg\.?\s*bal)"
)
_CLOSING_RE = re.compile(
    r"(?i)\b(closing|số\s*dư?\s*cuối|cuối\s*(năm|kỳ)|ending|balance\s*c/?f|end\.?\s*bal)"
)
_MOVEMENT_RE = re.compile(
    r"(?i)\b(increase|decrease|addition|disposal|tăng|giảm|mua\s*mới|thanh\s*lý|"
    r"depreciation|khấu\s*hao|amortization|amortisation|impairment|revaluation|transfer|"
    r"written\s*off|write[\s-]*off|reclassification|reclassified|"
    r"charge\s*for\s*the\s*(year|period)|paid|repayment|settled|"
    r"proceeds|receipts|provision|reversal|adjustment|exchange\s*difference)"
)
_TOTAL_RE = re.compile(
    r"(?i)^\s*(total|subtotal|tổng|cộng|cộng\s*lại|grand\s*total)\s*$"
)
_SECTION_HEADER_RE = re.compile(r"(?i)^\s*([IVX]+\.?|\d+\.\s+[A-Z]|[A-Z]\s*\))\s*")
# P4: Accounting section headers (Cost, Accumulated depreciation, NBV, etc.)
_ACCOUNTING_SECTION_RE = re.compile(
    r"(?i)^\s*(cost|nguyên\s*giá|accumulated\s*depreciation|khấu\s*hao\s*lũy\s*kế|"
    r"accumulated\s*amortis[sz]ation|hao\s*mòn\s*lũy\s*kế|"
    r"net\s*book\s*value|giá\s*trị\s*còn\s*lại|carrying\s*amount|value\s*in\s*use|"
    r"provision|dự\s*phòng|fair\s*value|giá\s*trị\s*hợp\s*lý|"
    r"depreciated\s*value|giá\s*trị\s*hao\s*mòn)\s*$"
)

# Listing/metadata-style headings where totals are not expected and vertical
# sum rules should generally be suppressed.
_LISTING_HEADING_RE = re.compile(
    r"(?i)(detailed\s+by|related\s+(parties|companies)|"
    r"borrowings?\s*(–|-|—)?\s*$|loan\s+agreement|interest\s+rate|"
    r"equity\s+investment|number\s+of\s+shares|transaction\s+value|"
    r"non-cash|equivalent\s+vnd)"
)


def _normalize_text(s: Any) -> str:
    """Lowercase, strip, normalize unicode. Empty/NaN -> ''."""
    if s is None or (isinstance(s, float) and pd.isna(s)):
        return ""
    t = str(s).strip().lower()
    t = unicodedata.normalize("NFKC", t)
    return t


def normalize_heading(heading: Any) -> str:
    """Normalized heading used for semantics/routing.

    Phase 1: delegate to _normalize_text so that TABLES_WITHOUT_TOTAL and other
    heading-based gates can converge on a single normalization strategy.
    """
    return _normalize_text(heading)


def _numeric_density(series: pd.Series) -> float:
    """Fraction of cells that parse as numeric (Policy A: sufficient density = amount column)."""
    if series.empty:
        return 0.0
    from .numeric_utils import normalize_numeric_column

    parsed = series.map(normalize_numeric_column)
    numeric_count = parsed.notna().sum()
    return float(numeric_count / len(series))


def _text_density(series: pd.Series) -> float:
    """Fraction of non-null cells with non-empty string after normalize."""
    if series.empty:
        return 0.0
    non_null = series.notna()
    if non_null.sum() == 0:
        return 0.0
    non_empty = series.map(lambda x: bool(_normalize_text(x)), na_action="ignore")
    return float(non_empty.fillna(False).sum() / max(non_null.sum(), 1))


def _detect_label_col(df: pd.DataFrame) -> str | None:
    """Column with highest text density and low numeric rate (first such column)."""
    if df.empty or len(df.columns) == 0:
        return None
    best_col: str | None = None
    best_score = -1.0
    for col in df.columns:
        ser = df[col]
        text_d = _text_density(ser)
        num_d = _numeric_density(ser)
        if text_d >= TEXT_DENSITY_THRESHOLD and num_d < 0.5:
            score = text_d * (1.0 - num_d)
            if score > best_score:
                best_score = score
                best_col = str(col)
    return best_col


# Patch 3 (P1): Header-token filter — exclude non-money numeric columns
# Patch D: extended to cover shares, days, and pure year headers
_NON_MONEY_HEADER_RE = re.compile(
    r"(?i)(year\s*(of\s*maturity)?|năm\s*(đáo\s*hạn)?|"
    r"interest\s*rate|lãi\s*suất|%|percent|tỷ\s*lệ|"
    r"quantity|số\s*lượng|number\s*of|maturity\s*date|ngày\s*đáo\s*hạn|"
    r"shares?\b|days?\b|ngày\b)"
)


def _detect_amount_cols(
    df: pd.DataFrame,
    label_col: str | None,
    *,
    threshold: float = NUMERIC_DENSITY_THRESHOLD,
) -> list[str]:
    """Policy A: all columns with numeric density >= threshold (excluding label_col).

    Patch 3: columns whose header matches _NON_MONEY_HEADER_RE are excluded
    (year-of-maturity, interest rate, %, quantity, etc.).
    """
    if df.empty:
        return []
    out: list[str] = []
    skip = {label_col} if label_col else set()
    for col in df.columns:
        c = str(col)
        if c in skip:
            continue
        if _NON_MONEY_HEADER_RE.search(c):
            continue
        if _numeric_density(df[col]) >= threshold:
            # Patch D: year-value heuristic — exclude columns where >50% values
            # are in [2000, 2099] range (likely year values, not amounts)
            from .numeric_utils import normalize_numeric_column

            vals = df[col].map(normalize_numeric_column).dropna()
            if len(vals) > 0:
                year_frac = ((vals >= 2000) & (vals <= 2099)).sum() / len(vals)
                if year_frac > 0.5:
                    continue
            out.append(c)
    return out


def plan_note_validation(
    *,
    is_movement_table: bool,
    structure_status: StructureStatus,
    heading_normalized: str,
    segments: list[Segment],
    scopes: list[Scope],
) -> NoteValidationMode:
    """Decide how NOTE rules should treat this table.

    The planner is intentionally conservative and only distinguishes a few
    coarse archetypes that are stable enough to drive routing:

    - MOVEMENT_BY_ROWS: roll-forward style movement table with OB/CB and
      movement rows (per-segment).
    - GENERIC_NUMERIC_NOTE: non-movement numeric table with at least one
      vertical-sum scope.
    - LISTING_NO_TOTAL: headings explicitly declared as NO_TOTAL or known
      listing/metadata tables where totals are not expected.
    - UNDETERMINED: everything else; used to gate rules in a deny-by-default
      fashion.
    """

    from quality_audit.config.constants import TABLES_WITHOUT_TOTAL

    heading_lower = (heading_normalized or "").strip().lower()
    status = structure_status

    # Movement roll-forward has highest precedence.
    if is_movement_table:
        return NoteValidationMode.MOVEMENT_BY_ROWS

    # Explicit NO_TOTAL semantics from structure_status or heading.  These tables
    # are treated as listings with no expected totals even if incidental numeric
    # patterns appear.
    if (
        status is StructureStatus.STRUCTURE_NO_TOTAL
        or heading_lower in TABLES_WITHOUT_TOTAL
    ):
        return NoteValidationMode.LISTING_NO_TOTAL

    # Listing-style headings can either have no totals at all or have implicit
    # block-level totals that the planner discovered as scopes.
    is_listing_heading = bool(
        status is StructureStatus.STRUCTURE_LISTING
        or _LISTING_HEADING_RE.search(heading_lower)
    )
    if is_listing_heading:
        if scopes:
            return NoteValidationMode.LISTING_TOTALS
        return NoteValidationMode.LISTING_NO_TOTAL

    # Generic numeric note with scoped totals.
    if scopes:
        return NoteValidationMode.GENERIC_NUMERIC_NOTE

    # Fallback: we don't have enough information to classify safely.
    return NoteValidationMode.UNDETERMINED


def _classify_row_type(row_text: str, has_numeric: bool = True) -> RowType:
    """Classify row from concatenated label-cell text.

    Args:
        row_text: Label text of the row.
        has_numeric: Whether any amount column in this row has a numeric value.
            When False, movement-like labels become SECTION_HEADER (P4).
    """
    t = _normalize_text(row_text)
    if not t or t in ("nan", ""):
        # P1: blank label but row has numeric data → treat as data row, not BLANK
        if has_numeric:
            return RowType.OTHER
        return RowType.BLANK
    if _OPENING_RE.search(t):
        return RowType.OPENING
    if _CLOSING_RE.search(t):
        return RowType.CLOSING
    if _TOTAL_RE.search(t):
        return RowType.TOTAL_LIKE
    # P4: Accounting section headers (e.g., "Accumulated depreciation", "Cost")
    if _ACCOUNTING_SECTION_RE.match(t):
        return RowType.SECTION_HEADER
    if _MOVEMENT_RE.search(t):
        # P4: If movement keyword present but row has no numeric → section header
        if not has_numeric:
            return RowType.SECTION_HEADER
        return RowType.MOVEMENT
    if (
        _SECTION_HEADER_RE.match(t) or (len(t) < 80 and t.count(" ") <= 3)
    ) and re.match(r"^\s*([IVX]+\.?|\d+\.)\s*$", t):
        return RowType.SECTION_HEADER
    return RowType.OTHER


@dataclass
class Segment:
    """One segment (e.g. one asset class) with OB/CB/movement row indices."""

    start_row: int
    end_row: int
    ob_row_idx: int | None
    cb_row_idx: int | None
    movement_rows: list[int]
    confidence: float
    segment_name: str = ""


@dataclass
class Scope:
    """One vertical-sum scope: detail rows and total row index."""

    detail_rows: list[int]
    total_row_idx: int


@dataclass
class NoteStructureResult:
    """Result of analyze_note_table."""

    label_col: str | None
    amount_cols: list[str]
    row_types: list[RowType]
    segments: list[Segment]
    scopes: list[Scope]
    is_movement_table: bool
    # Existing aggregate confidence used by current routing logic.
    confidence: float
    # Phase 1: split structural vs alignment confidence for future routing.
    confidence_struct: float
    confidence_alignment: float
    # Phase 1: semantic mode and coarse structural status; defaulted here and
    # refined in later phases without breaking existing callers.
    mode: NoteMode
    structure_status: StructureStatus
    # Phase 2: central NOTE validation planner output used for rule routing.
    validation_mode: NoteValidationMode
    # Normalized heading cached for downstream consumers.
    heading_normalized: str
    # Optional planner payload for specialised executors (e.g. movement-by-columns).
    note_validation_plan: dict[str, Any] | None = field(default=None)


def _detect_movement_by_columns_plan(
    df: pd.DataFrame, amount_cols: list[str]
) -> dict[str, Any] | None:
    """Conservative detector for movement-by-columns layouts.

    We only trigger when:
    - There is exactly one opening-like amount column.
    - There is exactly one closing-like amount column.
    - There is at least one movement-like amount column in between.

    All pattern matching is done on column headers using the existing
    OPENING/CLOSING/MOVEMENT regexes. When in doubt, we return None so that
    the planner can fall back to MOVEMENT_BY_ROWS or generic modes.
    """
    if not amount_cols:
        return None

    cols = list(df.columns)
    # Map column name -> index for ordering checks.
    idx_by_name = {str(c): i for i, c in enumerate(cols)}

    opening_cols: list[str] = []
    closing_cols: list[str] = []
    movement_cols: list[str] = []

    for c in amount_cols:
        name = str(c)
        norm = _normalize_text(name)
        if _OPENING_RE.search(norm):
            opening_cols.append(name)
        if _CLOSING_RE.search(norm):
            closing_cols.append(name)
        if _MOVEMENT_RE.search(norm):
            movement_cols.append(name)

    if len(opening_cols) != 1 or len(closing_cols) != 1 or not movement_cols:
        return None

    ob_col = opening_cols[0]
    cb_col = closing_cols[0]
    # Require that OB and CB (and all movement columns) exist in the DataFrame.
    if ob_col not in idx_by_name or cb_col not in idx_by_name:
        return None
    for m in movement_cols:
        if m not in idx_by_name:
            return None

    ob_idx = idx_by_name[ob_col]
    cb_idx = idx_by_name[cb_col]
    # OB must come before CB with at least one movement column between them.
    if not (ob_idx < cb_idx):
        return None

    # All movement columns must lie between OB and CB.
    between: list[str] = []
    for m in movement_cols:
        mi = idx_by_name[m]
        if ob_idx < mi < cb_idx:
            between.append(m)
    if not between:
        return None

    return {"ob_col": ob_col, "cb_col": cb_col, "movement_cols": between}


# Netting (gross/less/net) detection for multi-section notes.
_NETTING_LESS_LEXICON = frozenset(
    {
        "less",
        "deduct",
        "deduction",
        "deductions",
        "contra revenue",
        "returns",
        "discounts",
        "allowances",
        "trừ",
        "giảm trừ",
    }
)
_NETTING_NET_EXCLUDE = frozenset({"book value"})


def _detect_hierarchical_netting_plan(
    df: pd.DataFrame,
    *,
    label_col: str | None,
    amount_cols: list[str],
    max_dist_strict: int = 5,
    max_dist_relaxed: int = 25,
) -> dict[str, Any] | None:
    """Detect a simple Total/Less/Net row triple for netting tables.

    This is intentionally conservative and only plans a netting validation when
    we find all three markers within a small adjacency window.
    """
    if df.empty or not amount_cols:
        return None

    label_ser = (
        df[label_col] if label_col and label_col in df.columns else df.iloc[:, 0]
    )

    total_rows: list[int] = []
    less_rows: list[int] = []
    net_rows: list[int] = []

    for idx in range(len(df)):
        row_text = _normalize_text(label_ser.iloc[idx])
        if not row_text:
            continue
        has_less = any(term in row_text for term in _NETTING_LESS_LEXICON)
        has_net = ("net" in row_text) and not any(
            ex in row_text for ex in _NETTING_NET_EXCLUDE
        )
        has_total = ("total" in row_text) or ("gross" in row_text)
        if has_total and not has_less and not has_net:
            total_rows.append(idx)
        elif has_less:
            less_rows.append(idx)
        elif has_net:
            net_rows.append(idx)

    if not (total_rows and less_rows and net_rows):
        return None

    def _within(max_dist: int) -> dict[str, Any] | None:
        for t in total_rows:
            for less_row in less_rows:
                for n in net_rows:
                    if max(t, less_row, n) - min(t, less_row, n) <= max_dist:
                        return {
                            "total_row_idx": t,
                            "less_row_idx": less_row,
                            "net_row_idx": n,
                            "amount_cols": list(amount_cols),
                            "max_dist": max_dist,
                        }
        return None

    return _within(max_dist_strict) or _within(max_dist_relaxed)


def _detect_listing_scopes_with_implicit_total(
    df: pd.DataFrame,
    label_col: str | None,
    amount_cols: list[str],
    row_types: list[RowType],
) -> list[Scope]:
    """Conservative detector for listing-style blocks with implicit totals.

    This helper works on one contiguous block at a time (between BLANK /
    SECTION_HEADER rows) and attempts to find a candidate total row that is
    corroborated by the detail rows above it for at least one amount column.
    """

    if not amount_cols or df.empty:
        return []

    from .numeric_utils import normalize_numeric_column

    n_rows = len(df)

    # Build a simple boolean mask for "numeric in any amount column".
    row_has_numeric: list[bool] = []
    for i in range(n_rows):
        has_num = False
        for ac in amount_cols:
            if ac in df.columns:
                parsed = normalize_numeric_column(df.iloc[i][ac])
                if parsed is not None and not (
                    isinstance(parsed, float) and pd.isna(parsed)
                ):
                    has_num = True
                    break
        row_has_numeric.append(has_num)

    # Helper to fetch normalized label text for a given row.
    if label_col and label_col in df.columns:
        label_series = df[label_col]
    else:
        label_series = df.iloc[:, 0]

    def _label_text(idx: int) -> str:
        return _normalize_text(label_series.iloc[idx])

    scopes: list[Scope] = []

    # Partition into blocks separated by BLANK / SECTION_HEADER rows.
    block_start = 0
    for i in range(n_rows + 1):
        is_separator = False
        if i == n_rows:
            is_separator = True
        else:
            rt = row_types[i] if i < len(row_types) else RowType.OTHER
            if rt in (RowType.BLANK, RowType.SECTION_HEADER):
                is_separator = True

        if not is_separator:
            continue

        block_end = i - 1
        if block_end >= block_start:
            # Collect numeric rows within this block.
            numeric_rows = [
                r for r in range(block_start, block_end + 1) if row_has_numeric[r]
            ]
            if len(numeric_rows) >= 3:
                # Consider last 1–2 numeric rows as candidate totals.
                candidate_idxs = numeric_rows[-2:]
                for cand_idx in reversed(candidate_idxs):
                    detail_rows = [r for r in numeric_rows if r < cand_idx]
                    if len(detail_rows) < 2:
                        continue

                    label_val = _label_text(cand_idx)
                    # Accept explicit TOTAL-like labels or blank labels as totals.
                    if label_val and not _TOTAL_RE.search(label_val):
                        continue

                    # Corroborate using at least one amount column.
                    corroborated = False
                    for ac in amount_cols:
                        if ac not in df.columns:
                            continue
                        col = df[ac].map(normalize_numeric_column)
                        cand_val = col.iloc[cand_idx]
                        if cand_val is None or (
                            isinstance(cand_val, float) and pd.isna(cand_val)
                        ):
                            continue
                        detail_vals = [
                            col.iloc[r]
                            for r in detail_rows
                            if col.iloc[r] is not None
                            and not (
                                isinstance(col.iloc[r], float) and pd.isna(col.iloc[r])
                            )
                        ]
                        if len(detail_vals) < 2:
                            continue
                        total_details = float(sum(detail_vals))
                        base = max(abs(total_details), abs(float(cand_val)))
                        # Loose tolerance scaled by magnitude; avoids spurious matches
                        # for small rounding noise while keeping the heuristic safe.
                        tol = max(base * 1e-6, 1e-6)
                        if abs(total_details - float(cand_val)) <= tol:
                            corroborated = True
                            break

                    if corroborated:
                        scopes.append(
                            Scope(detail_rows=list(detail_rows), total_row_idx=cand_idx)
                        )
                        break

        block_start = i + 1

    return scopes


def _split_segments(
    df: pd.DataFrame,
    row_types: list[RowType],
    label_col: str | None,
) -> list[Segment]:
    """Split table into segments at SECTION_HEADER/BLANK; infer OB/CB/movement per segment."""
    n = len(row_types)
    if n == 0:
        return []
    segments: list[Segment] = []
    start = 0
    while start < n:
        # P2: Segment ends ONLY at SECTION_HEADER (BLANK is treated as spacer, not splitter)
        end = start + 1
        while end < n:
            rt = row_types[end]
            if rt == RowType.SECTION_HEADER:
                break
            end += 1
        # Classify rows in [start, end)
        ob_idx: int | None = None
        cb_idx: int | None = None
        movement_rows: list[int] = []
        for i in range(start, end):
            rt = row_types[i]
            if rt == RowType.OPENING:
                ob_idx = i
            elif rt == RowType.CLOSING:
                cb_idx = i
            elif rt == RowType.MOVEMENT:
                movement_rows.append(i)
        # P1: Fallback movement_rows for roll-forward segments.
        # When OB+CB exist but no keyword-matched movements, default to all
        # data rows between OB..CB (excluding structural row types).
        has_ob = ob_idx is not None
        has_cb = cb_idx is not None
        has_mov = len(movement_rows) >= 1
        fallback_movement = False
        if has_ob and has_cb and not has_mov:
            _excluded = (
                RowType.BLANK,
                RowType.SECTION_HEADER,
                RowType.OPENING,
                RowType.CLOSING,
                RowType.TOTAL_LIKE,
            )
            movement_rows = [
                i for i in range(ob_idx + 1, cb_idx) if row_types[i] not in _excluded
            ]
            has_mov = len(movement_rows) >= 1
            fallback_movement = has_mov

        # Confidence: 1.0 if keyword-matched OB+CB+movement; 0.6 if fallback
        if has_ob and has_cb and has_mov:
            conf = 0.6 if fallback_movement else 1.0
        elif has_ob and has_cb:
            conf = 0.7
        elif has_ob or has_cb:
            conf = 0.4
        else:
            conf = 0.0
        seg_name = ""
        if label_col and label_col in df.columns and start < len(df):
            seg_name = _normalize_text(df.iloc[start][label_col])[:60]
        segments.append(
            Segment(
                start_row=start,
                end_row=end,
                ob_row_idx=ob_idx,
                cb_row_idx=cb_idx,
                movement_rows=movement_rows,
                confidence=conf,
                segment_name=seg_name,
            )
        )
        start = end
    return segments


# Patch 4 (P1): Subtotal/netting row exclusion regex
_SUBTOTAL_RE = re.compile(
    r"(?i)^\s*(subtotal|sub-total|gross|net|discount|less|cộng|tổng\s*phụ|"
    r"giảm\s*trừ|chiết\s*khấu)\b"
)


def _detect_scopes(
    df: pd.DataFrame,
    row_types: list[RowType],
    segments: list[Segment],
    amount_cols: list[str] | None = None,
    heading: str = "",
) -> list[Scope]:
    """Build scopes for vertical sum: total row + detail rows per block.

    Patch 2: heading-aware gating — tables in TABLES_WITHOUT_TOTAL skip
    the fallback "last numeric row as total" heuristic.
    Patch 4: subtotal/netting rows excluded from detail_rows.
    """
    # P4: Baseline rows that should NOT be included in sum-to-total blocks
    _baseline_re = re.compile(
        r"(?i)(accounting\s*profit|lợi\s*nhuận\s*kế\s*toán|profit\s*before\s*tax|"
        r"lợi\s*nhuận\s*trước\s*thuế|statutory\s*tax\s*rate|thuế\s*suất)"
    )
    # Patch 2 (P0): Gate fallback total for tables without explicit totals
    from quality_audit.config.constants import TABLES_WITHOUT_TOTAL

    _heading_lower = heading.strip().lower() if heading else ""
    _skip_fallback_total = _heading_lower in TABLES_WITHOUT_TOTAL

    # Patch C: Listing-table gate — skip fallback total for known listing/metadata headings
    _is_listing_table = bool(_LISTING_HEADING_RE.search(_heading_lower))
    scopes: list[Scope] = []
    for seg in segments:
        # Find total-like row in segment
        total_idx: int | None = None
        for i in range(seg.start_row, seg.end_row):
            if row_types[i] == RowType.TOTAL_LIKE:
                total_idx = i
                break
        # P4: Conservative secondary — last numeric row as total if segment has ≥3 rows
        # BUT only for sum-to-total segments, NOT roll-forward segments (which have OB/CB)
        # Patch 2: also skip when heading is in TABLES_WITHOUT_TOTAL
        seg_has_ob_cb = seg.ob_row_idx is not None or seg.cb_row_idx is not None
        if (
            total_idx is None
            and not seg_has_ob_cb
            and not _skip_fallback_total
            and not _is_listing_table
            and (seg.end_row - seg.start_row) >= 3
            and amount_cols
        ):
            from .numeric_utils import normalize_numeric_column

            # P1: Scan from end of segment backwards for first row with
            # high numeric density (≥2 amount cols with values).
            end_idx = seg.end_row - 1
            start_idx = seg.start_row
            for candidate in range(end_idx, start_idx, -1):
                if candidate >= len(df):
                    continue
                if row_types[candidate] in (
                    RowType.BLANK,
                    RowType.SECTION_HEADER,
                    RowType.OPENING,
                    RowType.CLOSING,
                ):
                    continue
                num_count = 0
                for ac in amount_cols:
                    if ac in df.columns:
                        v = normalize_numeric_column(df.iloc[candidate][ac])
                        if v is not None and not (isinstance(v, float) and pd.isna(v)):
                            num_count += 1
                if num_count >= min(2, len(amount_cols)):
                    total_idx = candidate
                    break
        if total_idx is None:
            continue
        # Build detail_rows excluding baseline, TOTAL_LIKE, and subtotal/netting rows
        detail_rows = []
        label_col_idx = 0
        for i in range(seg.start_row, total_idx):
            rt = row_types[i]
            if rt in (RowType.BLANK, RowType.TOTAL_LIKE):  # Patch 4: exclude TOTAL_LIKE
                continue
            # P4: Exclude baseline rows from sum blocks
            label_text = (
                _normalize_text(df.iloc[i].iloc[label_col_idx]) if i < len(df) else ""
            )
            if _baseline_re.search(label_text):
                continue
            # Patch 4: Exclude subtotal/netting rows
            if _SUBTOTAL_RE.search(label_text):
                continue
            detail_rows.append(i)
        if detail_rows or total_idx < seg.end_row:
            scopes.append(Scope(detail_rows=detail_rows, total_row_idx=total_idx))
    return scopes


def analyze_note_table(
    df: pd.DataFrame,
    heading: str,
    table_id: str | None = None,
) -> NoteStructureResult:
    """Analyze a NOTE table: label column, amount columns, row types, segments, scopes.

    Policy A: amount_cols = all columns with numeric density >= NUMERIC_DENSITY_THRESHOLD.
    Segments are split at SECTION_HEADER/BLANK; each segment gets ob_row_idx, cb_row_idx,
    movement_rows, and confidence. Scopes are built for vertical-sum rules.

    Args:
        df: Table DataFrame (header row already promoted).
        heading: Table heading text (for logging; not used in logic yet).
        table_id: Optional table identifier (e.g. "017").

    Returns:
        NoteStructureResult with label_col, amount_cols, row_types, segments, scopes,
        is_movement_table, and overall confidence.
    """
    _ = heading, table_id
    heading_normalized = normalize_heading(heading)
    if df.empty:
        return NoteStructureResult(
            label_col=None,
            amount_cols=[],
            row_types=[],
            segments=[],
            scopes=[],
            is_movement_table=False,
            confidence=0.0,
            confidence_struct=0.0,
            confidence_alignment=0.0,
            mode=NoteMode.UNDETERMINED,
            structure_status=StructureStatus.STRUCTURE_UNDETERMINED,
            validation_mode=NoteValidationMode.UNDETERMINED,
            heading_normalized=heading_normalized,
        )
    label_col = _detect_label_col(df)
    amount_cols = _detect_amount_cols(df, label_col)
    # Conservative movement-by-columns detection based solely on headers.
    movement_by_cols_plan = _detect_movement_by_columns_plan(df, amount_cols)
    # Build row text from first column or label_col
    label_col_ser = (
        df[label_col] if label_col and label_col in df.columns else df.iloc[:, 0]
    )
    # P4: Determine per-row numeric presence for SECTION_HEADER vs MOVEMENT
    from .numeric_utils import normalize_numeric_column

    row_has_numeric: list[bool] = []
    for i in range(len(df)):
        has_num = False
        for ac in amount_cols:
            if ac in df.columns:
                val = df.iloc[i][ac]
                parsed = normalize_numeric_column(val)
                if parsed is not None and not (
                    isinstance(parsed, float) and pd.isna(parsed)
                ):
                    has_num = True
                    break
        row_has_numeric.append(has_num)
    row_types = [
        _classify_row_type(
            _normalize_text(x),
            has_numeric=row_has_numeric[i] if i < len(row_has_numeric) else True,
        )
        for i, x in enumerate(label_col_ser)
    ]
    segments = _split_segments(df, row_types, label_col)
    scopes = _detect_scopes(
        df, row_types, segments, amount_cols=amount_cols, heading=heading
    )
    # is_movement_table: at least one segment with OB+CB+movement
    is_movement = any(
        s.ob_row_idx is not None
        and s.cb_row_idx is not None
        and len(s.movement_rows) >= 1
        for s in segments
    )
    # Overall confidence: max segment confidence if movement; else based on scopes
    seg_conf = max((s.confidence for s in segments), default=0.0)
    scope_conf = 1.0 if scopes else 0.0
    confidence = max(seg_conf, scope_conf * 0.8) if scopes else seg_conf
    # Phase 1: initial separation — keep semantics close to existing behavior.
    confidence_struct = seg_conf
    confidence_alignment = scope_conf
    # Phase 1: conservative defaults; later phases will derive richer modes.
    if is_movement and seg_conf > 0.0:
        mode = NoteMode.MOVEMENT_ROLLFORWARD
        structure_status = StructureStatus.STRUCTURE_OK
    elif scopes:
        mode = NoteMode.SCOPED_TOTAL
        structure_status = StructureStatus.STRUCTURE_OK
    else:
        mode = NoteMode.UNDETERMINED
        structure_status = StructureStatus.STRUCTURE_UNDETERMINED

    # Patch: explicit NO_TOTAL semantics for known headings.
    # Tables whose heading is in TABLES_WITHOUT_TOTAL are treated as listings
    # with no expected totals; they must not carry scopes or undetermined
    # structure status, otherwise downstream NOTE rules will emit noisy WARNs.
    from quality_audit.config.constants import TABLES_WITHOUT_TOTAL

    heading_lower = (heading_normalized or "").strip().lower()
    if heading_lower in TABLES_WITHOUT_TOTAL:
        scopes = []
        structure_status = StructureStatus.STRUCTURE_NO_TOTAL
    else:
        # For listing-style headings that are not in the hard NO_TOTAL list, we
        # allow a very conservative implicit-total detector to propose scopes.
        if _LISTING_HEADING_RE.search(heading_lower) and not scopes:
            listing_scopes = _detect_listing_scopes_with_implicit_total(
                df, label_col, amount_cols, row_types
            )
            if listing_scopes:
                scopes = listing_scopes

    # Netting tables (gross/less/net) should not be treated as undetermined;
    # they follow a different equation shape than global vertical sums.
    netting_plan = None
    if amount_cols and not is_movement:
        netting_plan = _detect_hierarchical_netting_plan(
            df, label_col=label_col, amount_cols=amount_cols
        )
        if netting_plan:
            mode = NoteMode.HIERARCHICAL_SUBTOTALS
            structure_status = StructureStatus.STRUCTURE_OK

    # Phase 2 planner: derive coarse validation mode for routing/gating.
    validation_mode = plan_note_validation(
        is_movement_table=is_movement,
        structure_status=structure_status,
        heading_normalized=heading_normalized,
        segments=segments,
        scopes=scopes,
    )

    note_validation_plan: dict[str, Any] | None = None
    # Movement-by-columns takes precedence over generic numeric modes when we
    # have a strong header-based plan and the table is not already classified
    # as movement-by-rows.
    if movement_by_cols_plan and not is_movement:
        validation_mode = NoteValidationMode.MOVEMENT_BY_COLUMNS
        note_validation_plan = movement_by_cols_plan
    elif netting_plan and not is_movement:
        validation_mode = NoteValidationMode.HIERARCHICAL_NETTING
        note_validation_plan = netting_plan

    return NoteStructureResult(
        label_col=label_col,
        amount_cols=amount_cols,
        row_types=row_types,
        segments=segments,
        scopes=scopes,
        is_movement_table=is_movement,
        confidence=confidence,
        confidence_struct=confidence_struct,
        confidence_alignment=confidence_alignment,
        mode=mode,
        structure_status=structure_status,
        validation_mode=validation_mode,
        heading_normalized=heading_normalized,
        note_validation_plan=note_validation_plan,
    )
