"""
2-phase skip classifier: footer/signature vs real financial table.

Only skip (treat as footer/signature) when Phase 1 (positive evidence) is strong
and Phase 2 (negative evidence: real financial data) is weak.
Used by word_reader, generic_validator, and audit_service.
"""

import logging
from typing import Dict, Tuple

import pandas as pd

logger = logging.getLogger(__name__)

# Phase 1: positive evidence — footer/signature keywords (case-insensitive)
FOOTER_SIGNATURE_KEYWORDS = [
    "signed",
    "director",
    "prepared by",
    "approved by",
    "authorised",
    "authorized",
    "chief accountant",
    "cfo",
    "chief financial officer",
    "chief executive officer",
    "ceo",
    "signature",
    "reviewed by",
    "managing director",
    "general director",
    "board of directors",
    "auditor",
    "date:",
    "ký tên",
    "chữ ký",
    "người lập",
    "được ủy quyền",
    "đã phê duyệt",
    "người xem xét",
    "kế toán trưởng",
    "giám đốc tài chính",
    "tổng giám đốc",
    "giám đốc điều hành",
]

# Phase 2: negative evidence — row-label patterns suggesting real financial table (equity/capital etc.)
FINANCIAL_TABLE_ROW_LABELS = [
    "share capital",
    "number of shares",
    "par value",
    "contributed capital",
    "equity",
    "vốn",
    "cổ phần",
    "vốn cổ phần",
    "vốn điều lệ",
    "capital",
    "issued",
    "ordinary shares",
    "preference shares",
    "treasury shares",
    "legal reserve",
    "other reserves",
    "retained earnings",
    "undistributed",
    "assets",
    "tài sản",
    "liabilities",
    "nợ",
    "borrowings",
    "vay",
    "revenue",
    "doanh thu",
    "expenses",
    "chi phí",
    "profit",
    "lợi nhuận",
    "cash",
    "tiền",
    "receivables",
    "phải thu",
    "payables",
    "phải trả",
    "inventory",
    "hàng tồn kho",
]


def _numeric_cell_ratio(df: pd.DataFrame) -> float:
    """Fraction of cells that look numeric."""
    if df.empty:
        return 0.0
    total = 0
    numeric = 0
    for row in df.values:
        for cell in row:
            if pd.isna(cell):
                total += 1
                continue
            total += 1
            s = str(cell).strip()
            cleaned = (
                s.replace(",", "")
                .replace(".", "")
                .replace("-", "")
                .replace(" ", "")
                .lstrip("-")
            )
            if cleaned.isdigit() or (
                len(cleaned) > 0 and cleaned.replace(".", "", 1).isdigit()
            ):
                numeric += 1
    return numeric / total if total > 0 else 0.0


def _all_text_lower(df: pd.DataFrame) -> str:
    """Single string of all cell text (lower)."""
    if df.empty:
        return ""
    return " ".join(
        str(cell).lower()
        for row in df.values
        for cell in row
        if pd.notna(cell) and str(cell).strip()
    )


def _has_short_lines(df: pd.DataFrame, max_chars: int = 80) -> bool:
    """True if many rows are very short (typical of signature blocks)."""
    if df.empty or len(df) < 2:
        return False
    short = 0
    for row in df.values:
        line = " ".join(str(c) for c in row if pd.notna(c)).strip()
        if len(line) <= max_chars and line:
            short += 1
    return short >= max(1, len(df) // 2)


def classify_footer_signature(df: pd.DataFrame, heading: str = "") -> Tuple[bool, Dict]:
    """
    2-phase classifier: only return should_skip=True when positive evidence
    (footer/signature) is strong and negative evidence (real financial table) is weak.

    Phase 1 (positive): footer/signature keywords, small table, low numeric density, short lines.
    Phase 2 (negative): financial row labels (share capital, equity, vốn, cổ phần, etc.),
    year patterns (20xx, 19xx), currency symbols, high numeric density.

    Args:
        df: Table DataFrame.
        heading: Optional heading text (used for context in evidence).

    Returns:
        (should_skip, evidence): should_skip=True only when phase1 strong and phase2 weak.
        evidence contains positive_hits, negative_hits, numeric_ratio, final_decision, etc.
    """
    evidence: Dict = {
        "positive_hits": [],
        "negative_hits": [],
        "numeric_ratio": 0.0,
        "phase1_strong": False,
        "phase2_strong": False,
        "final_decision": "do_not_skip",
    }
    if df.empty:
        evidence["final_decision"] = "do_not_skip"
        return False, evidence

    all_text = _all_text_lower(df)
    numeric_ratio = _numeric_cell_ratio(df)
    row_count = len(df)
    evidence["numeric_ratio"] = round(numeric_ratio, 4)
    evidence["row_count"] = row_count

    # Phase 1: positive evidence (footer/signature)
    positive_hits = [k for k in FOOTER_SIGNATURE_KEYWORDS if k in all_text]
    evidence["positive_hits"] = positive_hits
    has_footer_keyword = len(positive_hits) > 0
    small_table = row_count <= 20
    low_numeric = numeric_ratio < 0.1
    very_low_numeric = numeric_ratio < 0.05
    short_lines = _has_short_lines(df)
    evidence["short_lines"] = short_lines

    phase1_strong = (
        has_footer_keyword
        and small_table
        and (low_numeric or (row_count <= 5 and very_low_numeric) or short_lines)
    )
    # Also allow: very small table with very low numeric (no keyword required for tiny blocks)
    if row_count <= 3 and very_low_numeric and short_lines:
        phase1_strong = phase1_strong or len(positive_hits) >= 1
    evidence["phase1_strong"] = phase1_strong

    # Phase 2: negative evidence (real financial table)
    negative_hits = [k for k in FINANCIAL_TABLE_ROW_LABELS if k in all_text]
    evidence["negative_hits"] = negative_hits
    has_financial_labels = len(negative_hits) > 0
    has_year = "20" in all_text or "19" in all_text
    has_currency = any(
        x in all_text
        for x in ["vnd", "usd", "%", "percent", "million", "thousand", "triệu", "nghìn"]
    )
    high_numeric = numeric_ratio > 0.15
    very_high_numeric = numeric_ratio > 0.30

    phase2_strong = (
        has_financial_labels
        or (high_numeric and (has_year or has_currency))
        or very_high_numeric
    )
    evidence["phase2_strong"] = phase2_strong
    evidence["has_year"] = has_year
    evidence["has_currency"] = has_currency

    should_skip = phase1_strong and not phase2_strong
    evidence["final_decision"] = "skip" if should_skip else "do_not_skip"

    if should_skip:
        logger.debug(
            "Skip classifier: skip (footer/signature). positive_hits=%s, negative_hits=%s",
            len(positive_hits),
            len(negative_hits),
        )
    else:
        if phase2_strong:
            logger.debug(
                "Skip classifier: do not skip (financial content). negative_hits=%s",
                negative_hits[:5],
            )

    return should_skip, evidence
