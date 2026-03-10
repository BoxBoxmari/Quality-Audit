"""
MovementByColumnsRule — roll-forward validation for movement-by-columns tables.

Validates that Opening Balance + Sum(Movements) = Closing Balance, using a
header-based planner payload from the NOTE structure engine. This is a
minimal, happy-path executor intended for clearly-identified movement-by-
columns notes; when in doubt, the planner should fall back to the existing
movement-by-rows or generic numeric modes.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

import pandas as pd

from quality_audit.core.evidence import Severity, ValidationEvidence
from quality_audit.core.rules.base_rule import AuditRule

if TYPE_CHECKING:
    from quality_audit.core.materiality import MaterialityEngine


class MovementByColumnsRule(AuditRule):
    """
    Minimal executor for movement-by-columns notes.

    For each row where OB/CB and all movement columns are populated and
    numeric, checks OB + Sum(movements) == CB within dynamic tolerance.
    Emits at most one FAIL evidence when a discrepancy is found.
    """

    rule_id = "MOVEMENT_BY_COLUMNS"
    description = "Số dư cuối kỳ (cột) = Số dư đầu kỳ (cột) + Biến động (các cột)"
    severity_default = Severity.MAJOR
    table_types = ["GENERIC_NOTE"]

    def evaluate(
        self,
        df: pd.DataFrame,
        *,
        materiality: MaterialityEngine,
        table_type: str,
        table_id: str | None = None,
        amount_cols: list[str] | None = None,
        note_validation_mode: str | None = None,
        note_validation_plan: dict[str, Any] | None = None,
        **kwargs: Any,
    ) -> list[ValidationEvidence]:
        evidence_list: list[ValidationEvidence] = []

        # Hard gate: only run when the planner has explicitly classified the
        # table as movement-by-columns and provided a usable plan.
        if note_validation_mode != "MOVEMENT_BY_COLUMNS":
            return evidence_list

        if not note_validation_plan:
            return evidence_list

        ob_col = note_validation_plan.get("ob_col")
        cb_col = note_validation_plan.get("cb_col")
        movement_cols = note_validation_plan.get("movement_cols") or []

        if not ob_col or not cb_col or not movement_cols:
            return evidence_list

        if ob_col not in df.columns or cb_col not in df.columns:
            return evidence_list
        for c in movement_cols:
            if c not in df.columns:
                return evidence_list

        # Helper: parse numeric values; non-numeric/NaN -> None.
        def _to_number(val: Any) -> float | None:
            try:
                num = pd.to_numeric(val)
            except (TypeError, ValueError):
                return None
            if isinstance(num, float) and pd.isna(num):
                return None
            return float(num)

        n_rows = len(df)
        for i in range(n_rows):
            ob_raw = df.iloc[i][ob_col]
            cb_raw = df.iloc[i][cb_col]
            ob_val = _to_number(ob_raw)
            cb_val = _to_number(cb_raw)
            if ob_val is None or cb_val is None:
                continue

            mov_vals: list[float] = []
            fully_populated = True
            for c in movement_cols:
                mv_raw = df.iloc[i][c]
                mv_val = _to_number(mv_raw)
                if mv_val is None:
                    fully_populated = False
                    break
                mov_vals.append(mv_val)

            if not fully_populated:
                continue

            expected_cb = ob_val + sum(mov_vals)
            diff = expected_cb - cb_val
            # Baseline magnitude consistent with MovementEquationRule.
            magnitude = max(abs(ob_val), abs(cb_val))
            tol = materiality.compute(magnitude, table_type)
            if abs(diff) > tol:
                evidence_list.append(
                    ValidationEvidence(
                        rule_id=self.rule_id,
                        assertion_text=(
                            "Movement-by-columns equation failed: "
                            f"{ob_col} + sum(movements) != {cb_col}"
                        ),
                        expected=expected_cb,
                        actual=cb_val,
                        diff=diff,
                        tolerance=tol,
                        is_material=abs(diff) > tol,
                        severity=self.severity_default,
                        table_type=table_type,
                        table_id=table_id,
                        source_rows=[i],
                        source_cols=[ob_col, *movement_cols, cb_col],
                        metadata={
                            "row_index": i,
                            "ob_col": ob_col,
                            "cb_col": cb_col,
                            "movement_cols": movement_cols,
                            "note_validation_mode": note_validation_mode,
                        },
                    )
                )
                # Emit only a single FAIL for now to keep signal low-noise.
                break

        return evidence_list

