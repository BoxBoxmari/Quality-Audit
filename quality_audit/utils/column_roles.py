"""
Column role inference for financial tables (Spine fix 1).

Provides a single mechanism to classify each column as CODE, LABEL, NUMERIC, or OTHER.
All sum/total/compare and CY/PY mapping must use these roles to exclude CODE absolutely.
"""

import logging
import re
from typing import Any, Dict, List, Optional, Tuple

import pandas as pd

from ..config.feature_flags import get_feature_flags
from .column_detector import ColumnDetector
from .numeric_utils import normalize_numeric_column

logger = logging.getLogger(__name__)

# Header-based code column detection (no dependency on TableNormalizer to avoid circular import).
# Include Vietnamese synonyms: ms, số, tt so "Mã số", "MS", "Số", "STT", "TT" are detected as CODE.
_CODE_HEADER_PATTERN = re.compile(
    r"^(code|no\.?|stt|mã|ma|ms|số|tt|ref\.?|index|num|id|number|item|account|acct|line|row)(\.\d+)?$",
    re.IGNORECASE,
)
_CODE_PREFIXES = (
    "mã số ",
    "thuyết minh ",
    "particulars ",
    "description ",
    "nội dung ",
    "line item ",
    "chỉ tiêu ",
)


def _normalize_header(col_name: str) -> str:
    """Normalize header for comparison (same semantics as TableNormalizer.normalize_header)."""
    return " ".join(str(col_name).strip().lower().split())


def _is_code_column_by_header(normalized_header: str) -> bool:
    """True if header indicates a code column (exclude from sum/total/CY/PY)."""
    if _CODE_HEADER_PATTERN.match(normalized_header):
        return True
    for prefix in _CODE_PREFIXES:
        if normalized_header.startswith(prefix) or normalized_header == prefix.rstrip():
            return True
    return False


ROLE_CODE = "CODE"
ROLE_LABEL = "LABEL"
ROLE_NUMERIC = "NUMERIC"
ROLE_OTHER = "OTHER"

NUMERIC_DENSITY_THRESHOLD = 0.25
NUMERIC_CONFIDENCE_HIGH = 0.8
CODE_HEADER_STRONG_CONFIDENCE = 0.9


def infer_column_roles(
    df: pd.DataFrame,
    header_row: int = 0,
    context: Optional[Dict[str, Any]] = None,
) -> Tuple[Dict[str, str], Dict[str, float], Dict[str, Any]]:
    """
    Classify each column role: CODE, LABEL, NUMERIC, or OTHER.

    Used globally so that every aggregator/sum/total-row compare ignores ROLE_CODE
    and never selects ROLE_CODE as CY/PY or amount column.

    Args:
        df: DataFrame with table data (columns = header row).
        header_row: Row index used as header (0-based); for evidence only.
        context: Optional dict (e.g. table_id, heading) for logging.

    Returns:
        roles: Dict[column_name, role] with values CODE | LABEL | NUMERIC | OTHER.
        confidences: Dict[column_name, float] in [0, 1].
        evidence: Dict with per_column numeric_density, token_patterns, header_hint,
            and lists chosen_numeric_columns, excluded_code_columns.
    """
    context = context or {}
    table_id = context.get("table_id") or context.get("heading") or ""

    columns = [str(c).strip() for c in df.columns]
    roles: Dict[str, str] = {}
    confidences: Dict[str, float] = {}
    evidence_per_col: Dict[str, Dict[str, Any]] = {}

    # When there are no rows, classify by header only (no content-based metrics).
    if df.empty:
        for col in columns:
            header_norm = _normalize_header(col)
            header_lower = str(col).strip().lower()
            header_hint = "none"
            if re.search(r"\d{4}", header_lower) or re.search(
                r"cy|py|năm|year", header_lower
            ):
                header_hint = "year"
            if re.search(r"vnd|usd|eur|₫|\$|€|đồng", header_lower):
                header_hint = "currency" if header_hint == "none" else header_hint
            if "%" in str(col) or "percent" in header_lower:
                header_hint = "percent" if header_hint == "none" else header_hint
            if _is_code_column_by_header(header_norm):
                roles[col] = ROLE_CODE
                confidences[col] = CODE_HEADER_STRONG_CONFIDENCE
            elif header_hint in ("year", "currency", "percent"):
                roles[col] = ROLE_NUMERIC
                confidences[col] = 0.6
            else:
                roles[col] = ROLE_OTHER
                confidences[col] = 0.5
        chosen_numeric = [c for c in columns if roles.get(c) == ROLE_NUMERIC]
        excluded_code = [c for c in columns if roles.get(c) == ROLE_CODE]
        evidence = {
            "per_column": {},
            "chosen_numeric_columns": chosen_numeric,
            "excluded_code_columns": excluded_code,
            "header_row": header_row,
        }
        logger.info(
            "table_id=%s (no rows) chosen_numeric_columns=%s excluded_code_columns=%s",
            table_id,
            chosen_numeric,
            excluded_code,
        )
        return roles, confidences, evidence

    # Non-empty DataFrame: full content-based inference (reuse vars from above).
    roles = {}
    confidences = {}
    evidence_per_col = {}

    note_col = ColumnDetector.detect_note_column(df)

    for col in columns:
        col_evidence: Dict[str, Any] = {}
        header_lower = str(col).strip().lower()
        header_norm = _normalize_header(col)
        series = df[col]

        non_empty = series.astype(str).str.strip()
        non_empty_mask = (non_empty != "") & (non_empty.str.lower() != "nan")
        n_non_empty = int(non_empty_mask.sum())

        if n_non_empty == 0:
            numeric_density = 0.0
        else:
            parsed = series.astype(object).map(normalize_numeric_column)
            parseable_count = int(parsed.notna().sum())
            numeric_density = float(parseable_count / n_non_empty)
        col_evidence["numeric_density"] = numeric_density

        header_hint = "none"
        if re.search(r"\d{4}", header_lower) or re.search(
            r"cy|py|năm|year", header_lower
        ):
            header_hint = "year"
        # Ticket-3: Recognise movement/roll-forward column headers
        if re.search(
            r"opening|closing|addition|additions|disposal|disposals"
            r"|tăng|giảm|đầu kỳ|cuối kỳ|phát sinh|chuyển",
            header_lower,
        ):
            header_hint = "movement" if header_hint == "none" else header_hint
        if re.search(r"vnd|usd|eur|₫|\$|€|đồng", header_lower):
            header_hint = "currency" if header_hint == "none" else header_hint
        if "%" in str(col) or "percent" in header_lower:
            header_hint = "percent" if header_hint == "none" else header_hint
        if re.search(r"amount|figures?|amounts", header_lower):
            header_hint = "amount" if header_hint == "none" else header_hint
        if re.search(r"\btotal\b|\btổng\b", header_lower):
            header_hint = "total" if header_hint == "none" else header_hint
        col_evidence["header_hint"] = header_hint

        uniqueness = 0.0
        if n_non_empty > 0:
            unique_vals = series[non_empty_mask].astype(str).nunique()
            uniqueness = float(unique_vals / n_non_empty)
        col_evidence["uniqueness"] = uniqueness

        sample_vals = series[non_empty_mask].astype(str).head(20)
        avg_len = float(sample_vals.str.len().mean()) if len(sample_vals) else 0.0
        col_evidence["avg_value_length"] = avg_len

        token_patterns = []
        non_null = series.dropna().astype(str)
        first_val = non_null.iloc[0] if len(non_null) > 0 else ""
        if re.search(r"\d{4}", str(first_val)):
            token_patterns.append("year_like")
        col_evidence["token_patterns"] = token_patterns

        evidence_per_col[col] = col_evidence

        if _is_code_column_by_header(header_norm):
            roles[col] = ROLE_CODE
            confidences[col] = CODE_HEADER_STRONG_CONFIDENCE
            continue
        if note_col and col == note_col:
            roles[col] = ROLE_LABEL
            confidences[col] = 0.85
            continue
        # Year/currency/percent/amount/total/movement columns are never CODE.
        if header_hint in (
            "year",
            "currency",
            "percent",
            "amount",
            "total",
            "movement",
        ):
            roles[col] = ROLE_NUMERIC
            confidences[col] = 0.6
            continue

        # Content-based: short numeric-looking values with ambiguous header -> CODE (e.g. account codes).
        ambiguous_code_headers = frozenset(
            ("unknown", "desc", "ref", "no", "id", "code", "stt", "tt", "ms", "number")
        )
        if (
            numeric_density >= NUMERIC_DENSITY_THRESHOLD
            and header_norm in ambiguous_code_headers
            and avg_len < 6
            and uniqueness > 0.5
        ):
            roles[col] = ROLE_CODE
            confidences[col] = 0.75
            continue

        if numeric_density >= NUMERIC_DENSITY_THRESHOLD and (
            header_hint
            in ("year", "currency", "percent", "amount", "total", "movement")
            or numeric_density >= 0.5
        ):
            roles[col] = ROLE_NUMERIC
            confidences[col] = min(0.95, 0.5 + numeric_density * 0.5)
        elif (
            numeric_density < 0.2
            and (avg_len < 15 or uniqueness > 0.9)
            and uniqueness > 0.2
        ):
            roles[col] = ROLE_CODE
            confidences[col] = 0.75
        else:
            roles[col] = ROLE_OTHER
            confidences[col] = 0.5

    chosen_numeric = [c for c in columns if roles.get(c) == ROLE_NUMERIC]
    excluded_code = [c for c in columns if roles.get(c) == ROLE_CODE]

    # Group 3/4 fallback: when no chosen_numeric, treat last two non-CODE columns as NUMERIC if density > 0.1
    if (
        not chosen_numeric
        and len(columns) >= 2
        and get_feature_flags().get("use_last_two_columns_fallback", False)
    ):
        non_code = [c for c in columns if roles.get(c) != ROLE_CODE]
        if len(non_code) >= 2:
            last_two = non_code[-2:]
            densities = [
                evidence_per_col.get(c, {}).get("numeric_density", 0) for c in last_two
            ]
            if all(d >= 0.1 for d in densities):
                for c in last_two:
                    roles[c] = ROLE_NUMERIC
                    confidences[c] = min(
                        0.7,
                        0.5
                        + evidence_per_col.get(c, {}).get("numeric_density", 0) * 0.4,
                    )
                chosen_numeric = [c for c in columns if roles.get(c) == ROLE_NUMERIC]
                logger.info(
                    "table_id=%s use_last_two_columns_fallback: chosen_numeric_columns=%s",
                    table_id,
                    chosen_numeric,
                )

    evidence = {
        "per_column": evidence_per_col,
        "chosen_numeric_columns": chosen_numeric,
        "excluded_code_columns": excluded_code,
        "header_row": header_row,
    }

    logger.info(
        "table_id=%s chosen_numeric_columns=%s excluded_code_columns=%s",
        table_id,
        chosen_numeric,
        excluded_code,
    )
    return roles, confidences, evidence


def get_columns_to_exclude_from_sum(
    roles: Dict[str, str],
    include_note: bool = True,
    include_percent: bool = True,
) -> List[str]:
    """
    Return column names that must never be included in sum/total/compare.

    Always includes all ROLE_CODE columns. If include_note is True, also includes
    the single ROLE_LABEL column (note/particulars) when present.
    If include_percent is True, excludes columns whose name suggests percentage
    (e.g. "percent", "%") from sum checks.

    Args:
        roles: Dict from infer_column_roles.
        include_note: If True, exclude ROLE_LABEL (note column) from sums.
        include_percent: If True, exclude columns with header hint "percent" or "%".

    Returns:
        List of column names to exclude.
    """
    exclude = [c for c, r in roles.items() if r == ROLE_CODE]
    if include_note:
        label_cols = [c for c, r in roles.items() if r == ROLE_LABEL]
        exclude.extend(label_cols)
    if include_percent:
        percent_cols = [
            c for c in roles if "percent" in str(c).lower() or "%" in str(c)
        ]
        exclude.extend(percent_cols)
    return exclude


def get_numeric_column_names(roles: Dict[str, str]) -> List[str]:
    """
    Return column names with ROLE_NUMERIC, in original order.

    Used for amount columns, CY/PY selection, and total comparison.
    """
    return [c for c, r in roles.items() if r == ROLE_NUMERIC]


def infer_column_roles_and_exclude(
    df: pd.DataFrame,
    header_row: int = 0,
    context: Optional[Dict[str, Any]] = None,
) -> Tuple[Dict[str, str], Dict[str, float], Dict[str, Any], List[str]]:
    """
    Convenience: infer roles and return exclude list for sum/total.

    Returns:
        roles, confidences, evidence, exclude_list (CODE + optional LABEL).
    """
    roles, confidences, evidence = infer_column_roles(df, header_row, context)
    exclude = get_columns_to_exclude_from_sum(roles, include_note=True)
    return roles, confidences, evidence, exclude
