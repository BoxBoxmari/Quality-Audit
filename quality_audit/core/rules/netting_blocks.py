"""
NettingBlocksRule — validation for gross/less/net style notes.

This is a pure executor: it only runs when the NOTE planner explicitly sets
note_validation_mode=HIERARCHICAL_NETTING and provides the planned row indices.
"""

from __future__ import annotations

from typing import Any

import pandas as pd

from quality_audit.core.evidence import Severity, ValidationEvidence
from quality_audit.core.rules.base_rule import AuditRule


class NettingBlocksRule(AuditRule):
    rule_id = "NETTING_BLOCKS"
    description = "Net = Total - Less (gross/less/net)"
    severity_default = Severity.MAJOR
    table_types = ["GENERIC_NOTE", "TAX_NOTE"]

    def evaluate(
        self,
        df: pd.DataFrame,
        *,
        materiality,
        table_type: str,
        table_id: str | None = None,
        amount_cols: list[str] | None = None,
        note_validation_mode: str | None = None,
        note_validation_plan: dict[str, Any] | None = None,
        **kwargs: Any,
    ) -> list[ValidationEvidence]:
        if str(note_validation_mode or "") != "HIERARCHICAL_NETTING":
            return []
        if not note_validation_plan:
            return []

        total_row_idx = note_validation_plan.get("total_row_idx")
        less_row_idx = note_validation_plan.get("less_row_idx")
        net_row_idx = note_validation_plan.get("net_row_idx")
        planned_amount_cols = note_validation_plan.get("amount_cols") or []

        if (
            total_row_idx is None
            or less_row_idx is None
            or net_row_idx is None
            or not planned_amount_cols
        ):
            return []

        cols = (
            [c for c in planned_amount_cols if c in df.columns]
            if planned_amount_cols
            else []
        )
        if not cols:
            cols = [c for c in (amount_cols or []) if c in df.columns]
        if not cols:
            return []

        evidence_list: list[ValidationEvidence] = []
        for col in cols:
            total_val = self._parse_float(df.iloc[int(total_row_idx)][col])
            less_val = self._parse_float(df.iloc[int(less_row_idx)][col])
            net_val = self._parse_float(df.iloc[int(net_row_idx)][col])

            # Sign-safe: if Less is already negative (common presentation),
            # expected net becomes total + less.
            expected_net = total_val + less_val if less_val < 0 else total_val - less_val
            tol = materiality.compute(abs(expected_net), table_type)
            diff = net_val - expected_net

            meta = {
                "note_validation_mode": str(note_validation_mode or ""),
                "total_row_idx": int(total_row_idx),
                "less_row_idx": int(less_row_idx),
                "net_row_idx": int(net_row_idx),
                "amount_col": col,
                "less_is_negative": less_val < 0,
            }

            if abs(diff) > tol:
                evidence_list.append(
                    ValidationEvidence.fail_evidence(
                        rule_id=self.rule_id,
                        assertion_text="Net = Total - Less",
                        expected=expected_net,
                        actual=net_val,
                        tolerance=tol,
                        severity=self.severity_default,
                        source_rows=[int(total_row_idx), int(less_row_idx), int(net_row_idx)],
                        source_cols=[col],
                        table_type=table_type,
                        table_id=table_id,
                        metadata=meta,
                    )
                )
                # Keep signal low-noise: one FAIL per table is sufficient.
                break

            # Emit INFO evidence to avoid "unverified numeric table" WARNs.
            evidence_list.append(
                ValidationEvidence(
                    rule_id=self.rule_id,
                    assertion_text="Net = Total - Less",
                    expected=expected_net,
                    actual=net_val,
                    diff=diff,
                    tolerance=tol,
                    is_material=False,
                    severity=Severity.INFO,
                    confidence=1.0,
                    source_rows=[int(total_row_idx), int(less_row_idx), int(net_row_idx)],
                    source_cols=[col],
                    table_type=table_type,
                    table_id=table_id,
                    metadata=meta,
                )
            )

        return evidence_list
