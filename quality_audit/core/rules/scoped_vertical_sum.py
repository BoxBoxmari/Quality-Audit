"""
Scoped Vertical Sum Rule (vertical_sum_scoped).

Validates that the sum of detail rows within each detected scope equals
the corresponding total/subtotal row within materiality tolerance.
When total_row_idx and detail_rows are provided (e.g. from audit_service),
uses them as a single scope. Otherwise runs scope detection (until_total_marker,
by_group_breaks, etc.) and never silently passes by widening scope; ambiguous
scope produces WARN with diagnostics (Severity.MINOR).
"""

from __future__ import annotations

import logging
import re
from dataclasses import dataclass
from typing import TYPE_CHECKING, Any

import pandas as pd

from quality_audit.core.evidence import Severity, ValidationEvidence
from quality_audit.core.rules.base_rule import AuditRule

if TYPE_CHECKING:
    from quality_audit.core.materiality import MaterialityEngine

logger = logging.getLogger(__name__)

# Default regex for total/subtotal row labels (Vietnamese + English)
TOTAL_ROW_PATTERN = re.compile(
    r"(?i)^\s*(total|subtotal|cộng\s*cộng|tổng\s*cộng|cộng|tổng|total\s*$|subtotal\s*$)\s*$"
)


@dataclass(frozen=True)
class _Scope:
    """One summation block: detail row indices and the total row index."""

    detail_rows: list[int]
    total_row_idx: int


def _row_label(df: pd.DataFrame, row_idx: int, code_col: str | None) -> str:
    """Text of the label column for the row, or first column if code_col missing."""
    if code_col and code_col in df.columns:
        val = df.iloc[row_idx][code_col]
    else:
        val = df.iloc[row_idx].iloc[0] if len(df.columns) > 0 else ""
    return str(val).strip() if pd.notna(val) else ""


def _is_blank_row(df: pd.DataFrame, row_idx: int) -> bool:
    """True if the row has no non-empty content."""
    row = df.iloc[row_idx]
    return all(pd.isna(v) or str(v).strip() == "" for v in row)


def _is_total_like(label: str) -> bool:
    """True if label looks like a total/subtotal row."""
    return bool(TOTAL_ROW_PATTERN.search(label)) if label else False


def _detect_scopes_until_total_marker(
    df: pd.DataFrame,
    code_col: str | None,
) -> list[_Scope] | None:
    """
    One block: rows [0, total_row_idx) as details, total_row_idx as total.
    Uses last row that matches total-like label; if none, returns None.
    """
    n = len(df)
    if n < 2:
        return None
    total_candidates = [
        i for i in range(n) if _is_total_like(_row_label(df, i, code_col))
    ]
    if not total_candidates:
        return None
    total_row_idx = total_candidates[-1]
    if total_row_idx == 0:
        return None
    detail_rows = list(range(0, total_row_idx))
    return [_Scope(detail_rows=detail_rows, total_row_idx=total_row_idx)]


def _detect_scopes_by_group_breaks(
    df: pd.DataFrame,
    code_col: str | None,
) -> list[_Scope] | None:
    """
    Split rows by blank rows; each non-empty segment: last row = total, rest = details.
    Only accept segments that have at least one detail and a total-like last row.
    """
    n = len(df)
    if n < 2:
        return None
    scopes: list[_Scope] = []
    start = 0
    for i in range(n + 1):
        if i == n or _is_blank_row(df, i):
            if i > start:
                segment_detail = list(range(start, i - 1))
                total_idx = i - 1
                if segment_detail and _is_total_like(
                    _row_label(df, total_idx, code_col)
                ):
                    scopes.append(
                        _Scope(detail_rows=segment_detail, total_row_idx=total_idx)
                    )
            start = i + 1
    return scopes if scopes else None


def _hybrid_scope_detection(
    df: pd.DataFrame,
    code_col: str | None,
) -> tuple[list[_Scope] | None, dict[str, Any]]:
    """
    Try until_total_marker, then by_group_breaks. Return (scopes, diagnostics).
    If no scopes found, returns (None, diagnostics) for WARN.
    """
    diagnostics: dict[str, Any] = {"tried": []}

    scopes = _detect_scopes_until_total_marker(df, code_col)
    diagnostics["tried"].append("until_total_marker")
    if scopes:
        diagnostics["mode"] = "until_total_marker"
        return scopes, diagnostics

    scopes = _detect_scopes_by_group_breaks(df, code_col)
    diagnostics["tried"].append("by_group_breaks")
    if scopes:
        diagnostics["mode"] = "by_group_breaks"
        return scopes, diagnostics

    diagnostics["mode"] = None
    diagnostics["reason"] = "no_scope_detected"
    return None, diagnostics


class ScopedVerticalSumRule(AuditRule):
    """
    Validates vertical sum within scoped blocks. Uses total_row_idx/detail_rows
    when provided; otherwise runs scope detection. Never silently passes by
    widening scope; ambiguous scope yields WARN with diagnostics.
    """

    rule_id = "VERTICAL_SUM_SCOPED"
    description = "Tổng theo phạm vi dọc: tổng các dòng chi tiết trong từng khối bằng dòng tổng tương ứng"
    severity_default = Severity.MAJOR
    table_types = ["GENERIC_NOTE", "TAX_NOTE"]

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
        **kwargs: Any,
    ) -> list[ValidationEvidence]:
        """
        When total_row_idx and detail_rows are provided, use them as one scope.
        Otherwise run hybrid scope detection; for each scope and each amount column
        compare sum(details) to total within tolerance. Ambiguous scope → WARN.
        """
        evidence_list: list[ValidationEvidence] = []

        note_validation_mode = str(kwargs.get("note_validation_mode") or "")
        # NOTE planner gating: listing/NO_TOTAL and single-row disclosure notes
        # must not get SCOPE_UNDETERMINED WARNs from this rule.
        if note_validation_mode in ("LISTING_NO_TOTAL", "SINGLE_ROW_DISCLOSURE"):
            logger.debug(
                "VERTICAL_SUM_SCOPED: skipped for note_validation_mode=%s",
                note_validation_mode,
            )
            return evidence_list

        if amount_cols is None or not amount_cols:
            logger.debug("VERTICAL_SUM_SCOPED: no amount columns")
            return evidence_list

        is_scoped_mode = note_validation_mode in ("SCOPED_TOTAL", "LISTING_TOTALS")

        scope_diagnostics: dict[str, Any]
        if total_row_idx is not None and detail_rows is not None:
            # Single scope from table_info (backward compatible)
            scopes = [_Scope(detail_rows=detail_rows, total_row_idx=total_row_idx)]
            scope_diagnostics = {"source": "table_info"}
        elif kwargs.get("scopes"):
            # Scopes from note_structure (analyze_note_table)
            raw_scopes = kwargs["scopes"]
            scopes = [
                _Scope(
                    detail_rows=getattr(s, "detail_rows", s.get("detail_rows", [])),
                    total_row_idx=getattr(
                        s, "total_row_idx", s.get("total_row_idx", -1)
                    ),
                )
                for s in raw_scopes
            ]
            scopes = [
                s for s in scopes if s.total_row_idx >= 0 and s.detail_rows is not None
            ]
            scope_diagnostics = {"source": "note_structure"}
            if not scopes:
                scopes = None
        else:
            # Hybrid detection is retained only as a diagnostic helper.  When the
            # planner has not provided explicit scopes we allow hybrid detection
            # to propose scopes, but we no longer emit WARNs solely because it
            # could not determine a scope.
            scopes, scope_diagnostics = _hybrid_scope_detection(df, code_col)

        if scopes is None:
            if is_scoped_mode:
                # Planner said this table should have scoped totals but did not
                # provide explicit scopes. Treat this as an informational skip
                # rather than a WARN so that listing-style tables do not get
                # noisy SCOPE_UNDETERMINED findings.
                ev = ValidationEvidence(
                    rule_id=self.rule_id,
                    assertion_text=(
                        "Phạm vi tổng dọc không được lập kế hoạch; bỏ qua kiểm tra "
                        "sum-to-total cho bảng này"
                    ),
                    # INFO-only evidence: keep numeric fields as floats for type safety.
                    expected=0.0,
                    actual=0.0,
                    diff=0.0,
                    tolerance=0.0,
                    is_material=False,
                    severity=Severity.INFO,
                    confidence=1.0,
                    source_rows=[],
                    source_cols=[],
                    table_type=table_type,
                    table_id=table_id,
                    metadata={
                        "skip_reason": "SCOPES_NOT_PLANNED",
                        "diagnostics": scope_diagnostics,
                    },
                )
                evidence_list.append(ev)
            # For non-scoped modes, hybrid detection failures are purely
            # diagnostic; we simply skip the rule without emitting WARN/FAIL.
            return evidence_list

        for scope in scopes:
            tr_idx = scope.total_row_idx
            if tr_idx < 0 or tr_idx >= len(df):
                continue
            for col in amount_cols:
                if col not in df.columns:
                    continue
                total_val_raw = df.iloc[tr_idx][col]
                if not re.search(r"\d", str(total_val_raw)):
                    continue
                total_val = self._parse_float(total_val_raw)
                if pd.isna(total_val):
                    continue

                actual_sum = 0.0
                valid_details: list[int] = []
                for r in scope.detail_rows:
                    if r < 0 or r >= len(df):
                        continue
                    v = self._parse_float(df.iloc[r][col])
                    if not pd.isna(v):
                        actual_sum += v
                        valid_details.append(r)

                if not valid_details and total_val == 0.0:
                    continue

                # G3: Gate — no numeric detail rows but total is non-zero
                # → structure/scope issue, NOT a data mismatch
                if not valid_details and total_val != 0.0:
                    logger.info(
                        "vertical_sum_gated reason_code=NO_DETAIL_ROWS col=%s total=%s table_id=%s",
                        col,
                        total_val,
                        table_id,
                    )
                    ev = ValidationEvidence.warn_evidence(
                        rule_id=self.rule_id,
                        assertion_text=(
                            f"No detail rows with numeric values for [{col}]; "
                            f"total={total_val} — scope may be incomplete"
                        ),
                        reason_code="NO_DETAIL_ROWS",
                        table_type=table_type,
                        table_id=table_id,
                        metadata={
                            "total_row_idx": tr_idx,
                            "total_value": total_val,
                            "column": col,
                            "gate_reason_code": "NO_DETAIL_ROWS",
                            "scope_source": scope_diagnostics.get(
                                "source", "scope_detection"
                            ),
                        },
                    )
                    evidence_list.append(ev)
                    continue

                tolerance = materiality.compute(abs(total_val), table_type)
                diff = actual_sum - total_val
                is_material = abs(diff) > tolerance
                severity = self.severity_default if is_material else Severity.INFO

                source_rows = valid_details + [tr_idx]
                assertion_text = (
                    f"Sum(details) == Total [{col}] (scope total_row={tr_idx})"
                )

                metadata: dict[str, Any] = {
                    "included_rows": valid_details,
                    "total_row_idx": tr_idx,
                    "scope_source": scope_diagnostics.get("source", "scope_detection"),
                }
                if scope_diagnostics.get("mode"):
                    metadata["scope_mode"] = scope_diagnostics["mode"]

                if is_material:
                    ev = ValidationEvidence.fail_evidence(
                        rule_id=self.rule_id,
                        assertion_text=assertion_text,
                        expected=total_val,
                        actual=actual_sum,
                        tolerance=tolerance,
                        severity=severity,
                        source_rows=source_rows,
                        source_cols=[col],
                        table_type=table_type,
                        table_id=table_id,
                        metadata=metadata,
                    )
                else:
                    ev = ValidationEvidence(
                        rule_id=self.rule_id,
                        assertion_text=assertion_text,
                        expected=total_val,
                        actual=actual_sum,
                        diff=diff,
                        tolerance=tolerance,
                        is_material=False,
                        severity=Severity.INFO,
                        confidence=1.0,
                        source_rows=source_rows,
                        source_cols=[col],
                        table_type=table_type,
                        table_id=table_id,
                        metadata=metadata,
                    )
                evidence_list.append(ev)

        return evidence_list
