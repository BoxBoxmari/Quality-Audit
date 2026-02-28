"""
Structural Fingerprinter — content-based table classification signals.

Extracts structural evidence from table content (code patterns, keyword
presence, row structure) independently of heading text. This is the
core input for TableClassifierV2's weighted voting system.
"""

from __future__ import annotations

import logging
import re
from dataclasses import dataclass, field
from typing import Dict, FrozenSet, List, Optional, Set

import pandas as pd

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# VAS / IFRS code pattern sets per statement type
# ---------------------------------------------------------------------------

# Balance Sheet: codes 100, 110, 120, ..., 270 (Assets), 300, 310, ..., 440 (L+E)
_BS_CODES: FrozenSet[str] = frozenset(
    {
        "100",
        "110",
        "120",
        "130",
        "140",
        "150",
        "200",
        "210",
        "220",
        "230",
        "240",
        "250",
        "260",
        "261",
        "262",
        "270",
        "300",
        "310",
        "311",
        "312",
        "313",
        "314",
        "315",
        "320",
        "330",
        "400",
        "410",
        "411",
        "412",
        "420",
        "421",
        "430",
        "440",
    }
)

# Income Statement: codes 01–62
_IS_CODES: FrozenSet[str] = frozenset(
    {
        "01",
        "02",
        "10",
        "11",
        "20",
        "21",
        "22",
        "23",
        "24",
        "25",
        "26",
        "30",
        "31",
        "32",
        "40",
        "50",
        "51",
        "52",
        "60",
        "61",
        "62",
    }
)

# Cash Flow: codes 01–70 (operating/investing/financing/net)
_CF_CODES: FrozenSet[str] = frozenset(
    {
        "01",
        "02",
        "03",
        "04",
        "05",
        "06",
        "07",
        "08",
        "09",
        "10",
        "11",
        "12",
        "13",
        "14",
        "15",
        "16",
        "17",
        "20",
        "21",
        "22",
        "23",
        "24",
        "25",
        "26",
        "27",
        "30",
        "31",
        "32",
        "33",
        "34",
        "35",
        "36",
        "40",
        "50",
        "60",
        "61",
        "70",
    }
)

# Codes exclusive to IS (not shared with CF)
_IS_EXCLUSIVE: FrozenSet[str] = frozenset({"23", "25", "26", "51", "52", "61", "62"})

# Codes exclusive to CF (not shared with IS)
_CF_EXCLUSIVE: FrozenSet[str] = frozenset({"08", "09", "13", "14", "15", "16", "17"})

# Movement table patterns
_OPENING_PATTERNS = re.compile(
    r"(?i)\b(opening|số\s*dư?\s*đầu|đầu\s*(năm|kỳ)|beginning|balance\s*b/?f|beg\.?\s*bal)"
)
_CLOSING_PATTERNS = re.compile(
    r"(?i)\b(closing|số\s*dư?\s*cuối|cuối\s*(năm|kỳ)|ending|balance\s*c/?f|end\.?\s*bal)"
)
_MOVEMENT_PATTERNS = re.compile(
    r"(?i)\b(increase|decrease|addition|disposal|tăng|giảm|mua\s*mới|thanh\s*lý|"
    r"depreciation|khấu\s*hao|amortization|impairment|revaluation|transfer)"
)


# ---------------------------------------------------------------------------
# Keyword maps for content scanning
# ---------------------------------------------------------------------------

_KEYWORD_MAP: Dict[str, List[str]] = {
    "assets": ["assets", "tài sản"],
    "liabilities": ["liabilities", "nợ phải trả"],
    "equity": ["equity", "vốn chủ sở hữu"],
    "cash": ["cash", "tiền"],
    "flows": ["flows", "lưu chuyển"],
    "revenue": ["revenue", "doanh thu", "sales", "thu nhập"],
    "profit": ["profit", "lợi nhuận", "lãi"],
    "operating": ["operating", "hoạt động kinh doanh"],
    "investing": ["investing", "hoạt động đầu tư"],
    "financing": ["financing", "hoạt động tài chính"],
}


@dataclass
class StructuralFingerprint:
    """Structural evidence extracted from table content.

    Attributes:
        found_codes: Set of numeric codes found in the table.
        code_density: Fraction of scanned rows containing a code.
        keywords_found: Set of keyword categories detected.
        bs_code_matches: Count of codes matching BS code set.
        is_code_matches: Count of codes matching IS code set.
        cf_code_matches: Count of codes matching CF code set.
        is_exclusive_matches: Codes matching IS-exclusive set.
        cf_exclusive_matches: Codes matching CF-exclusive set.
        has_opening: True if opening balance pattern detected.
        has_closing: True if closing balance pattern detected.
        movement_row_count: Number of rows with movement keywords.
        scan_rows: Number of rows scanned.
        total_rows: Total rows in table.
    """

    found_codes: Set[str] = field(default_factory=set)
    code_density: float = 0.0
    keywords_found: Set[str] = field(default_factory=set)
    bs_code_matches: int = 0
    is_code_matches: int = 0
    cf_code_matches: int = 0
    is_exclusive_matches: int = 0
    cf_exclusive_matches: int = 0
    has_opening: bool = False
    has_closing: bool = False
    movement_row_count: int = 0
    has_assets_in_early: bool = False
    scan_rows: int = 0
    total_rows: int = 0

    @property
    def has_movement_structure(self) -> bool:
        """True if table has opening + closing + at least 1 movement row."""
        return self.has_opening and self.has_closing and self.movement_row_count >= 1

    @property
    def keyword_score(self) -> float:
        """Fraction of keyword categories detected."""
        return len(self.keywords_found) / max(len(_KEYWORD_MAP), 1)


class StructuralFingerprinter:
    """Extract structural evidence from a table DataFrame.

    Usage::

        fp = StructuralFingerprinter()
        fingerprint = fp.extract(table)
        # fingerprint.bs_code_matches, fingerprint.has_movement_structure, etc.
    """

    _CODE_RE = re.compile(r"^\d{2,3}[a-zA-Z]?$")
    _CODE_DIGITS_RE = re.compile(r"^(\d{2,3})")
    _ROMAN_RE = re.compile(r"^[IVX]+$")

    def __init__(self, *, max_scan_rows: int = 60, early_window: int = 20) -> None:
        self.max_scan_rows = max_scan_rows
        self.early_window = early_window

    def extract(self, table: pd.DataFrame) -> StructuralFingerprint:
        """Extract structural fingerprint from table content.

        Args:
            table: DataFrame (post header-promotion).

        Returns:
            StructuralFingerprint with all evidence populated.
        """
        fp = StructuralFingerprint()
        fp.total_rows = len(table)

        if table.empty:
            return fp

        scan_rows = min(self.max_scan_rows, fp.total_rows)
        fp.scan_rows = scan_rows
        code_rows = 0

        for i in range(scan_rows):
            try:
                row_text = self._row_to_text(table, i)
            except Exception:
                continue

            # --- Keyword scanning ---
            for key, patterns in _KEYWORD_MAP.items():
                if any(p in row_text for p in patterns):
                    fp.keywords_found.add(key)

            # Early-window "assets" check
            if i < self.early_window and any(
                p in row_text for p in _KEYWORD_MAP["assets"]
            ):
                fp.has_assets_in_early = True

            # --- Movement pattern scanning ---
            if _OPENING_PATTERNS.search(row_text):
                fp.has_opening = True
            if _CLOSING_PATTERNS.search(row_text):
                fp.has_closing = True
            if _MOVEMENT_PATTERNS.search(row_text):
                fp.movement_row_count += 1

            # --- Code scanning (first 3 columns) ---
            for j in range(min(3, len(table.columns))):
                val = str(table.iloc[i, j]).strip()
                m = self._CODE_RE.match(val)
                if m:
                    digits = self._CODE_DIGITS_RE.match(val)
                    if digits:
                        fp.found_codes.add(digits.group(1))
                    code_rows += 1
                    break
                elif self._ROMAN_RE.match(val):
                    code_rows += 1
                    break

        fp.code_density = code_rows / scan_rows if scan_rows > 0 else 0.0

        # Count matches per statement type
        fp.bs_code_matches = len(fp.found_codes & _BS_CODES)
        fp.is_code_matches = len(fp.found_codes & _IS_CODES)
        fp.cf_code_matches = len(fp.found_codes & _CF_CODES)
        fp.is_exclusive_matches = len(fp.found_codes & _IS_EXCLUSIVE)
        fp.cf_exclusive_matches = len(fp.found_codes & _CF_EXCLUSIVE)

        return fp

    @staticmethod
    def _row_to_text(table: pd.DataFrame, row_idx: int) -> str:
        """Concatenate row values into lowercase text."""
        return " ".join(str(x).lower() for x in table.iloc[row_idx] if pd.notna(x))
