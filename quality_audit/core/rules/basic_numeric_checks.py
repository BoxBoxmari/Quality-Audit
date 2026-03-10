"""
BasicNumericChecksRule — fallback checks for numeric NOTE tables.

Runs when primary rules produce no evidence or when structure is undetermined.
Implements B1 (SimpleVerticalSum) and B2 (SimpleTieOut) as low-confidence checks.
"""

from __future__ import annotations

import logging
import re
from typing import Any

import pandas as pd

from ..evidence import Severity, ValidationEvidence
from .base_rule import AuditRule

logger = logging.getLogger(__name__)

_TOTAL_RE = re.compile(r"^(tổng|total|cộng|tổng cộng|grand total)\b", re.IGNORECASE)


class BasicNumericChecksRule(AuditRule):
    """Low-confidence numeric checks for NOTE tables.

    Activates when:
    - Table has amount_cols (is numeric)
    - AND (is_structure_undetermined OR low_confidence OR primary rules produced no evidence)

    Checks:
    - B1 SimpleVerticalSum: sum of detail rows ≈ total candidate
    - B2 SimpleTieOut: CB ≈ OB + movements (if OB/CB cols detected)
    """

    rule_id = "BASIC_NUMERIC_CHECKS"
    description = "Fallback vertical sum and tie-out for numeric NOTE tables"
    severity_default = Severity.MINOR

    def evaluate(
        self,
        df: pd.DataFrame,
        *,
        materiality: Any,
        table_type: str,
        table_id: str | None = None,
        code_col: str | None = None,
        amount_cols: list[str] | None = None,
        **kwargs: Any,
    ) -> list[ValidationEvidence]:
        evidence: list[ValidationEvidence] = []
        amount_cols = amount_cols or []
        if not amount_cols or df is None or df.empty:
            return evidence

        low_confidence = kwargs.get("low_confidence", False)
        label_col = kwargs.get("label_col")

        # Determine the label column for total-row detection
        if not label_col:
            # Use first non-amount column as label
            non_amount = [c for c in df.columns if c not in amount_cols]
            label_col = non_amount[0] if non_amount else None

        # B1: SimpleVerticalSum
        b1_evidence = self._check_vertical_sum(
            df,
            amount_cols,
            label_col,
            materiality,
            table_type,
            table_id,
            low_confidence,
        )
        evidence.extend(b1_evidence)

        # B2: SimpleTieOut (only if movement info available)
        ob_row_idx = kwargs.get("ob_row_idx")
        cb_row_idx = kwargs.get("cb_row_idx")
        movement_rows = kwargs.get("movement_rows")
        if ob_row_idx is not None and cb_row_idx is not None and movement_rows:
            b2_evidence = self._check_tie_out(
                df,
                amount_cols,
                ob_row_idx,
                cb_row_idx,
                movement_rows,
                materiality,
                table_type,
                table_id,
                low_confidence,
            )
            evidence.extend(b2_evidence)

        return evidence

    def _check_vertical_sum(
        self,
        df: pd.DataFrame,
        amount_cols: list[str],
        label_col: str | None,
        materiality: Any,
        table_type: str,
        table_id: str | None,
        low_confidence: bool,
    ) -> list[ValidationEvidence]:
        """B1: Find total candidates and verify sum of rows above."""
        evidence: list[ValidationEvidence] = []
        n = len(df)
        if n < 2:
            return evidence

        # Find total row candidates via label regex
        total_candidates: list[int] = []
        total_detection_strategy = "label_regex"
        if label_col and label_col in df.columns:
            for idx in range(n):
                cell = str(df.iloc[idx][label_col]).strip()
                if _TOTAL_RE.match(cell):
                    total_candidates.append(idx)

        # Fallback 1: scan backwards for last row with high numeric density
        if not total_candidates:
            total_detection_strategy = "last_numeric"
            for candidate in range(n - 1, 0, -1):
                num_count = 0
                for col in amount_cols:
                    if col in df.columns:
                        v = self._parse_float(df.iloc[candidate].get(col))
                        if v != 0.0:
                            num_count += 1
                if num_count >= min(2, len(amount_cols)):
                    total_candidates = [candidate]
                    break

        # Fallback 2: absolute last row
        if not total_candidates:
            total_detection_strategy = "last_row"
            total_candidates = [n - 1]

        tolerance = (
            materiality.get_tolerance() * 2.5
            if hasattr(materiality, "get_tolerance")
            else 1.0
        )

        for total_idx in total_candidates:
            detail_range = list(range(0, total_idx))
            if not detail_range:
                continue

            for col in amount_cols:
                if col not in df.columns:
                    continue

                total_val = self._parse_float(df.iloc[total_idx].get(col))
                # P1: total_val==0 with non-zero details → emit low-confidence WARN
                # instead of silently skipping

                detail_sum = sum(
                    self._parse_float(df.iloc[r].get(col)) for r in detail_range
                )

                diff = detail_sum - total_val
                is_material = abs(diff) > tolerance

                # Phase 3: Only treat B1 as a hard FAIL when we have a
                # computable, label-driven total. Heuristic totals (last_numeric
                # / last_row) are downgraded to safe diagnostics (INFO), so they
                # can surface as hints without driving Focus List FAILs.
                if total_detection_strategy == "label_regex":
                    is_material_flag = is_material
                    severity = Severity.MINOR if is_material else Severity.INFO
                else:
                    is_material_flag = False
                    severity = Severity.INFO

                meta = {
                    "check_engine": "basic_numeric",
                    "check_id": "B1_SimpleVerticalSum",
                    "low_confidence": low_confidence,
                    "total_row_idx": total_idx,
                    "detail_rows": detail_range,
                    "total_detection_strategy": total_detection_strategy,
                }

                ev = ValidationEvidence(
                    rule_id=self.rule_id,
                    assertion_text=(
                        f"B1 VerticalSum col={col}: "
                        f"sum(rows 0..{total_idx - 1})={detail_sum:,.0f} "
                        f"vs total(row {total_idx})={total_val:,.0f}"
                    ),
                    expected=total_val,
                    actual=detail_sum,
                    diff=diff,
                    tolerance=tolerance,
                    is_material=is_material_flag,
                    severity=severity,
                    confidence=0.5 if low_confidence else 0.7,
                    source_rows=[total_idx] + detail_range,
                    source_cols=[col],
                    table_type=table_type,
                    table_id=table_id,
                    metadata=meta,
                )
                evidence.append(ev)

        return evidence

    def _check_tie_out(
        self,
        df: pd.DataFrame,
        amount_cols: list[str],
        ob_row_idx: int,
        cb_row_idx: int,
        movement_rows: list[int],
        materiality: Any,
        table_type: str,
        table_id: str | None,
        low_confidence: bool,
    ) -> list[ValidationEvidence]:
        """B2: Verify CB ≈ OB + sum(movements)."""
        evidence: list[ValidationEvidence] = []
        tolerance = (
            materiality.get_tolerance() * 2.5
            if hasattr(materiality, "get_tolerance")
            else 1.0
        )

        for col in amount_cols:
            if col not in df.columns:
                continue

            ob_val = self._parse_float(df.iloc[ob_row_idx].get(col))
            cb_val = self._parse_float(df.iloc[cb_row_idx].get(col))
            mvmt_sum = sum(
                self._parse_float(df.iloc[r].get(col))
                for r in movement_rows
                if 0 <= r < len(df)
            )

            expected_cb = ob_val + mvmt_sum
            diff = cb_val - expected_cb
            is_material = abs(diff) > tolerance

            meta = {
                "check_engine": "basic_numeric",
                "check_id": "B2_SimpleTieOut",
                "low_confidence": low_confidence,
                "ob_row_idx": ob_row_idx,
                "cb_row_idx": cb_row_idx,
                "movement_rows": movement_rows,
            }

            ev = ValidationEvidence(
                rule_id=self.rule_id,
                assertion_text=(
                    f"B2 TieOut col={col}: "
                    f"OB({ob_val:,.0f}) + movements({mvmt_sum:,.0f}) "
                    f"= {expected_cb:,.0f} vs CB({cb_val:,.0f})"
                ),
                expected=expected_cb,
                actual=cb_val,
                diff=diff,
                tolerance=tolerance,
                is_material=is_material,
                severity=Severity.MINOR if is_material else Severity.INFO,
                confidence=0.5 if low_confidence else 0.7,
                source_rows=[ob_row_idx, cb_row_idx] + list(movement_rows),
                source_cols=[col],
                table_type=table_type,
                table_id=table_id,
                metadata=meta,
            )
            evidence.append(ev)

        return evidence
