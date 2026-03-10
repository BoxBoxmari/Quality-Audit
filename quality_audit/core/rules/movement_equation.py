"""
MovementEquationRule (replaces legacy roll-forward logic).

Validates that Opening Balance + Movements = Closing Balance,
respecting dynamic tolerances from the MaterialityEngine.
"""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING

import pandas as pd

from quality_audit.config.constants import WARN_REASON_STRUCTURE_INCOMPLETE
from quality_audit.core.evidence import Severity, ValidationEvidence
from quality_audit.core.rules.base_rule import AuditRule
from quality_audit.utils.note_structure import SEGMENT_CONFIDENCE_THRESHOLD

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
        table_id: str | None = None,
        code_col: str | None = None,
        amount_cols: list[str] | None = None,
        ob_row_idx: int | None = None,
        cb_row_idx: int | None = None,
        movement_rows: list[int] | None = None,
        **kwargs,
    ) -> list[ValidationEvidence]:
        """
        Evaluate OB + Movements == CB. When segments (from note_structure) are
        provided, evaluates per segment and per amount column; missing/ambiguous
        anchors yield WARN with STRUCTURE_INCOMPLETE.
        """
        evidence_list: list[ValidationEvidence] = []

        if amount_cols is None or not amount_cols:
            return evidence_list

        segments = kwargs.get("segments")
        is_movement_table = kwargs.get("is_movement_table", False)
        note_validation_mode = str(kwargs.get("note_validation_mode") or "")

        # Hard applicability gate for NOTE tables: when the planner has
        # classified a table as non‑movement (e.g. LISTING_NO_TOTAL), this rule
        # must not emit STRUCTURE_INCOMPLETE just because OB/CB anchors are
        # absent. Primary statement tables (which do not carry a
        # note_validation_mode) keep the previous behaviour.
        if note_validation_mode and note_validation_mode != "MOVEMENT_BY_ROWS":
            logger.debug(
                "MovementEquationRule: skipped for note_validation_mode=%s",
                note_validation_mode,
            )
            return evidence_list

        if segments:
            # P3: Regex for derived segments (NBV, carrying amount) — skip roll-forward
            import re as _re

            _nbv_re = _re.compile(
                r"(?i)(net\s*book\s*value|carrying\s*amount|gi[aá]\s*tr[iị]\s*c[oò]n\s*l[aạ]i|"
                r"nbv|depreciated\s*value)"
            )
            for seg in segments:
                # P3: Skip roll-forward for derived segments (NBV/carrying amount)
                if _nbv_re.search(seg.segment_name or ""):
                    evidence_list.append(
                        ValidationEvidence(
                            rule_id=self.rule_id,
                            assertion_text=(
                                f"Segment '{seg.segment_name}' is derived (NBV/carrying amount); "
                                f"roll-forward skipped"
                            ),
                            expected=0.0,
                            actual=0.0,
                            diff=0.0,
                            tolerance=0.0,
                            is_material=False,
                            severity=Severity.INFO,
                            table_type=table_type,
                            table_id=table_id,
                            source_rows=[],
                            source_cols=[],
                            metadata={
                                "segment_name": seg.segment_name,
                                "bounds": (seg.start_row, seg.end_row),
                                "nbv_derived": True,
                            },
                        )
                    )
                    continue
                if seg.confidence < SEGMENT_CONFIDENCE_THRESHOLD:
                    evidence_list.append(
                        ValidationEvidence.warn_evidence(
                            rule_id=self.rule_id,
                            assertion_text=(
                                f"Segment '{seg.segment_name or seg.start_row}' skipped (low confidence)"
                            ),
                            reason_code=WARN_REASON_STRUCTURE_INCOMPLETE,
                            table_type=table_type,
                            table_id=table_id,
                            metadata={
                                "segment_name": seg.segment_name,
                                "bounds": (seg.start_row, seg.end_row),
                                "confidence": seg.confidence,
                            },
                        )
                    )
                    continue
                if (
                    seg.ob_row_idx is None
                    or seg.cb_row_idx is None
                    or seg.movement_rows is None
                ):
                    if is_movement_table:
                        evidence_list.append(
                            ValidationEvidence.warn_evidence(
                                rule_id=self.rule_id,
                                assertion_text=(
                                    f"Segment '{seg.segment_name or seg.start_row}' structure incomplete"
                                ),
                                reason_code=WARN_REASON_STRUCTURE_INCOMPLETE,
                                table_type=table_type,
                                table_id=table_id,
                                metadata={
                                    "segment_name": seg.segment_name,
                                    "bounds": (seg.start_row, seg.end_row),
                                    "ob_row_idx": seg.ob_row_idx,
                                    "cb_row_idx": seg.cb_row_idx,
                                    "movement_rows": seg.movement_rows,
                                },
                            )
                        )
                    else:
                        logger.debug(
                            "MovementEquationRule: segment missing OB/CB/movement rows "
                            "but is_movement_table=False; skipping STRUCTURE_INCOMPLETE WARN"
                        )
                    continue
                max_idx = len(df) - 1
                ob_idx, cb_idx, mov_rows = (
                    seg.ob_row_idx,
                    seg.cb_row_idx,
                    seg.movement_rows,
                )
                if ob_idx > max_idx or cb_idx > max_idx:
                    evidence_list.append(
                        ValidationEvidence.warn_evidence(
                            rule_id=self.rule_id,
                            assertion_text=(
                                f"Segment '{seg.segment_name or seg.start_row}' OB/CB out of range"
                            ),
                            reason_code=WARN_REASON_STRUCTURE_INCOMPLETE,
                            table_type=table_type,
                            table_id=table_id,
                            metadata={
                                "segment_name": seg.segment_name,
                                "bounds": (seg.start_row, seg.end_row),
                                "ob_row_idx": ob_idx,
                                "cb_row_idx": cb_idx,
                            },
                        )
                    )
                    continue
                for col in amount_cols:
                    if col not in df.columns:
                        continue
                    ob_val = self._parse_float(df.iloc[ob_idx][col])
                    if pd.isna(ob_val):
                        continue
                    cb_val = self._parse_float(df.iloc[cb_idx][col])
                    if pd.isna(cb_val):
                        continue
                    movement_sum = 0.0
                    valid_moves = []
                    for r in mov_rows:
                        if r > max_idx:
                            continue
                        v = self._parse_float(df.iloc[r][col])
                        if not pd.isna(v):
                            movement_sum += v
                            valid_moves.append(r)
                    expected_cb = ob_val + movement_sum
                    magnitude = max(abs(ob_val), abs(cb_val))
                    tolerance = materiality.compute(magnitude, table_type)
                    assertion_text = f"OB + Movements == CB [{col}] (segment {seg.segment_name or seg.start_row})"
                    source_rows = [ob_idx] + valid_moves + [cb_idx]
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
                    evidence.metadata["segment_name"] = seg.segment_name
                    evidence.metadata["bounds"] = (seg.start_row, seg.end_row)
                    evidence_list.append(evidence)
            return evidence_list

        if ob_row_idx is None or cb_row_idx is None or movement_rows is None:
            if is_movement_table:
                evidence_list.append(
                    ValidationEvidence.warn_evidence(
                        rule_id=self.rule_id,
                        assertion_text="Movement structure incomplete (missing OB/CB/movement row indices)",
                        reason_code=WARN_REASON_STRUCTURE_INCOMPLETE,
                        table_type=table_type,
                        table_id=table_id,
                        metadata={
                            "ob_row_idx": ob_row_idx,
                            "cb_row_idx": cb_row_idx,
                            "movement_rows": movement_rows,
                        },
                    )
                )
            else:
                logger.debug("MovementEquationRule: missing structure parameters")
            return evidence_list

        max_idx = len(df) - 1
        if ob_row_idx > max_idx or cb_row_idx > max_idx:
            return evidence_list

        for col in amount_cols:
            if col not in df.columns:
                continue

            # 1. OB
            ob_val = self._parse_float(df.iloc[ob_row_idx][col])
            if pd.isna(ob_val):
                continue

            # 2. CB
            cb_val = self._parse_float(df.iloc[cb_row_idx][col])
            if pd.isna(cb_val):
                continue

            # 3. Movements
            movement_sum = 0.0
            valid_moves = []
            for r in movement_rows:
                if r > max_idx:
                    continue
                v = self._parse_float(df.iloc[r][col])
                if not pd.isna(v):
                    movement_sum += v
                    valid_moves.append(r)

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
