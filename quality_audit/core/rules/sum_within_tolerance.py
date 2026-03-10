"""
SumWithinTolerance Rule (replaces legacy rule_c).

Validates that the sum of detail rows equals the chosen total row
within the dynamically calculated materiality tolerance.
"""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING

import pandas as pd

from quality_audit.config.feature_flags import get_feature_flags
from quality_audit.core.evidence import Severity, ValidationEvidence
from quality_audit.core.rules.base_rule import AuditRule

if TYPE_CHECKING:
    from quality_audit.core.materiality import MaterialityEngine

logger = logging.getLogger(__name__)


class SumWithinToleranceRule(AuditRule):
    """
    Validates that a total row equals the sum of its preceding detail rows.
    """

    rule_id = "SUM_WITHIN_TOLERANCE"
    description = "Tổng các dòng chi tiết phải khớp với dòng tổng cộng"
    severity_default = Severity.MAJOR

    def evaluate(
        self,
        df: pd.DataFrame,
        *,
        materiality: MaterialityEngine,
        table_type: str,
        table_id: str | None = None,
        code_col: str | None = None,
        amount_cols: list[str] | None = None,
        total_row_idx: int | None = None,
        detail_rows: list[int] | None = None,
        **kwargs,
    ) -> list[ValidationEvidence]:
        """
        Evaluate the sum of details against the total row.

        Args:
            total_row_idx: Row index containing the total value.
            detail_rows: List of row indices to sum. If None, sums everything
                         above total_row_idx.
        """
        evidence_list: list[ValidationEvidence] = []
        get_feature_flags()

        if total_row_idx is None or total_row_idx < 0 or total_row_idx >= len(df):
            logger.debug("SumWithinToleranceRule: invalid or missing total_row_idx")
            return evidence_list

        if amount_cols is None or not amount_cols:
            logger.debug("SumWithinToleranceRule: no amount columns provided")
            return evidence_list

        if detail_rows is None:
            # Default: all rows strictly above the total row
            detail_rows = list(range(0, total_row_idx))

        if not detail_rows:
            return evidence_list

        # Evaluate column by column
        for col in amount_cols:
            if col not in df.columns:
                continue

            # 1. Extract total value
            total_val_raw = df.iloc[total_row_idx][col]
            import re

            if not re.search(r"\d", str(total_val_raw)):
                continue
            total_val = self._parse_float(total_val_raw)
            if pd.isna(total_val):
                continue

            # 2. Extract and sum details
            actual_sum = 0.0
            valid_details = []
            for r in detail_rows:
                v_raw = df.iloc[r][col]
                v = self._parse_float(v_raw)
                if not pd.isna(v):
                    actual_sum += v
                    valid_details.append(r)

            # Skip trivial columns (e.g. all empty)
            if not valid_details and total_val == 0.0:
                continue

            # 3. Compute dynamic tolerance
            # Sum rule uses total_val as the magnitude baseline
            tolerance = materiality.compute(abs(total_val), table_type)

            # 4. Generate evidence
            source_rows = valid_details + [total_row_idx]
            assertion_text = f"Sum(details) == Total [{col}]"

            # Use helper from base class
            evidence = self._make_evidence(
                assertion_text=assertion_text,
                expected=total_val,  # expected is the stated total
                actual=actual_sum,  # actual is the computed sum
                tolerance=tolerance,
                table_type=table_type,
                table_id=table_id,
                source_rows=source_rows,
                source_cols=[col],
            )
            evidence_list.append(evidence)

        return evidence_list
