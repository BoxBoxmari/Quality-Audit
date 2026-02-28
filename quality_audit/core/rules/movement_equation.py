"""
MovementEquationRule (replaces legacy roll-forward logic).

Validates that Opening Balance + Movements = Closing Balance,
respecting dynamic tolerances from the MaterialityEngine.
"""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING, List, Optional

import pandas as pd

from quality_audit.core.evidence import Severity, ValidationEvidence
from quality_audit.core.rules.base_rule import AuditRule

if TYPE_CHECKING:
    from quality_audit.core.materiality import MaterialityEngine


logger = logging.getLogger(__name__)


class MovementEquationRule(AuditRule):
    """
    Validates the roll-forward equation: OB + Sum(Movements) = CB.
    """

    rule_id = "MOVEMENT_EQUATION"
    description = "Số dư Cuối kỳ = Số dư Đầu kỳ + Biến động trong kỳ"
    severity_default = Severity.MAJOR
    table_types = ["GENERIC_NOTE", "FS_EQUITY"]

    def evaluate(
        self,
        df: pd.DataFrame,
        *,
        materiality: MaterialityEngine,
        table_type: str,
        table_id: Optional[str] = None,
        code_col: Optional[str] = None,
        amount_cols: Optional[List[str]] = None,
        ob_row_idx: Optional[int] = None,
        cb_row_idx: Optional[int] = None,
        movement_rows: Optional[List[int]] = None,
        **kwargs,
    ) -> List[ValidationEvidence]:
        """
        Evaluate OB + Movements == CB.

        Args:
            ob_row_idx: Opening balance row index.
            cb_row_idx: Closing balance row index.
            movement_rows: List of movement row indices.
        """
        evidence_list: List[ValidationEvidence] = []

        if ob_row_idx is None or cb_row_idx is None or movement_rows is None:
            logger.debug("MovementEquationRule: missing structure parameters")
            return evidence_list

        if amount_cols is None or not amount_cols:
            return evidence_list

        # Validate bounds
        max_idx = len(df) - 1
        if ob_row_idx > max_idx or cb_row_idx > max_idx:
            return evidence_list

        for col in amount_cols:
            if col not in df.columns:
                continue

            # 1. OB
            try:
                ob_val = float(df.iloc[ob_row_idx][col])
            except (ValueError, TypeError):
                continue

            # 2. CB
            try:
                cb_val = float(df.iloc[cb_row_idx][col])
            except (ValueError, TypeError):
                continue

            # 3. Movements
            movement_sum = 0.0
            valid_moves = []
            for r in movement_rows:
                if r > max_idx:
                    continue
                try:
                    v = float(df.iloc[r][col])
                    if not pd.isna(v):
                        movement_sum += v
                        valid_moves.append(r)
                except (ValueError, TypeError):
                    continue

            # Expected = OB + movements
            expected_cb = ob_val + movement_sum

            # Magnitude baseline is max(OB, CB)
            magnitude = max(abs(ob_val), abs(cb_val))
            tolerance = materiality.compute(magnitude, table_type)

            assertion_text = f"OB + Movements == CB [{col}]"
            source_rows = [ob_row_idx] + valid_moves + [cb_row_idx]

            evidence = self._make_evidence(
                assertion_text=assertion_text,
                expected=expected_cb,
                actual=cb_val,
                tolerance=tolerance,
                table_type=table_type,
                table_id=table_id,
                source_rows=source_rows,
                source_cols=[col],
            )
            evidence_list.append(evidence)

        return evidence_list
