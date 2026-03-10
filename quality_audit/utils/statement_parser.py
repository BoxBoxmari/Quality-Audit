"""
Robust statement parsing that handles duplicate codes explicitly.
"""

from collections import defaultdict
from dataclasses import dataclass, field
from typing import Dict, List, Optional

import pandas as pd

from .numeric_utils import parse_numeric


@dataclass
class StatementRow:
    """Represents a single row in a financial statement."""

    row_index: int
    code: str
    label: str
    values: Dict[str, float] = field(default_factory=dict)
    original_row: Optional[pd.Series] = None


class StatementParser:
    """
    Parses statement tables and provides semantic and code-based lookups.
    Avoids overwriting rows when duplicate codes occur.
    """

    def __init__(self, df: pd.DataFrame, code_col: str, cur_col: str, prior_col: str):
        self.code_col = code_col
        self.cur_col = cur_col
        self.prior_col = prior_col
        self.rows: List[StatementRow] = self._parse_rows(df)

        # Multi-map for optimized lookup
        self._code_map: Dict[str, List[StatementRow]] = defaultdict(list)
        for r in self.rows:
            if r.code:
                self._code_map[r.code].append(r)

    def _parse_rows(self, df: pd.DataFrame) -> List[StatementRow]:
        parsed = []
        for idx, row in df.iterrows():
            code_raw = row.get(self.code_col, "")
            label_raw = row.iloc[0] if len(row) > 0 else ""

            # Normalize code exactly like validators do (handled out of class or inside)
            # The caller passes normalized code or we retrieve it from the row directly.
            code_clean = str(code_raw).strip()

            cur_val = parse_numeric(row.get(self.cur_col, ""))
            prior_val = parse_numeric(row.get(self.prior_col, ""))

            stmt_row = StatementRow(
                row_index=idx,
                code=code_clean,
                label=str(label_raw),
                values={"CY": cur_val, "PY": prior_val},
                original_row=row,
            )
            parsed.append(stmt_row)
        return parsed

    def find_by_code(self, code: str) -> List[StatementRow]:
        """Find all rows matching an exact code."""
        return self._code_map.get(code, [])

    def find_by_label(self, text: str) -> List[StatementRow]:
        """Find rows containing specific text in their first column."""
        text_lower = text.lower()
        return [r for r in self.rows if text_lower in r.label.lower()]

    def aggregate_by_code(self, code: str) -> tuple[float, float]:
        """Aggregate CY and PY amounts for a given code."""
        matches = self.find_by_code(code)
        if not matches:
            return 0.0, 0.0

        cur_sum = sum(r.values.get("CY", 0.0) for r in matches)
        prior_sum = sum(r.values.get("PY", 0.0) for r in matches)
        return cur_sum, prior_sum
