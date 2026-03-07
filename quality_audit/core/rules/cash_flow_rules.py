"""
Cash Flow Rules.

Applies standard VAS/IFRS formula assertions for Statement of Cash Flows
based on line item codes.
"""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING

import pandas as pd

from quality_audit.core.evidence import Severity, ValidationEvidence
from quality_audit.core.rules.base_rule import AuditRule

if TYPE_CHECKING:
    from quality_audit.core.materiality import MaterialityEngine
    from quality_audit.core.model.statement_model_builder import (
        StatementModel,
        StatementRow,
    )


logger = logging.getLogger(__name__)

# Subtotal keywords for CF code 13 (label-based detection)
_CF20_SUBTOTAL_LABEL_KEYWORDS = (
    "subtotal",
    "cash generated from operations",
    "total from operating",
    "tổng từ hoạt động kinh doanh",
)


def _is_cf20_subtotal_row(row: StatementRow, model: StatementModel) -> bool:
    """
    Return True if this code-13 row is a subtotal row (do not add to 20).
    Uses label keywords first, then position (single 13 between 12 and 14).
    """
    if getattr(row, "code", "") != "13":
        return False
    label = (getattr(row, "label", None) or "").lower()
    for kw in _CF20_SUBTOTAL_LABEL_KEYWORDS:
        if kw in label:
            return True
    table_id = getattr(row, "table_id", "")
    rows_12_13_14 = [
        r
        for r in model.rows
        if getattr(r, "table_id", "") == table_id
        and getattr(r, "code", "") in ("12", "13", "14")
    ]
    rows_12_13_14.sort(key=lambda r: getattr(r, "source_idx", -1))
    code_13_rows = [r for r in rows_12_13_14 if getattr(r, "code", "") == "13"]
    if len(code_13_rows) != 1:
        return False
    idx_13 = rows_12_13_14.index(code_13_rows[0])
    has_12_before = any(getattr(r, "code", "") == "12" for r in rows_12_13_14[:idx_13])
    has_14_after = any(
        getattr(r, "code", "") == "14" for r in rows_12_13_14[idx_13 + 1 :]
    )
    return bool(has_12_before and has_14_after)


class CashFlowRules(AuditRule):
    """
    Validates standard Cash Flow formulas using item Codes.
    """

    rule_id = "CF_FORMULA_CHECK"
    description = "Kiểm tra các chỉ tiêu tính toán trên Lưu chuyển tiền tệ"
    severity_default = Severity.MAJOR
    table_types = ["FS_CASH_FLOW"]

    def evaluate_model(
        self, model: StatementModel, *, materiality: MaterialityEngine, **kwargs
    ) -> list[ValidationEvidence]:
        evidence_list: list[ValidationEvidence] = []
        if not model.rows:
            return evidence_list

        table_type = model.statement_type
        # Collect amount_cols from any row which has them
        amount_cols = set()
        for r in model.rows:
            amount_cols.update(r.values.keys())
        amount_cols = list(amount_cols)

        # Collect table_ids that have at least one CF row (from code 20 or any CF code)
        cf_table_ids = sorted(
            {r.table_id for r in model.rows if getattr(r, "table_id", "")}
        )
        if not cf_table_ids:
            return evidence_list

        def by_table(code: str, table_id: str):
            return [r for r in model.find_code(code) if r.table_id == table_id]

        def first_by_table(code: str, table_id: str):
            return next(iter(by_table(code, table_id)), None)

        for table_id in cf_table_ids:
            row_20 = first_by_table("20", table_id)
            row_30 = first_by_table("30", table_id)
            row_40 = first_by_table("40", table_id)
            row_50 = first_by_table("50", table_id)
            row_70 = first_by_table("70", table_id)
            row_08 = first_by_table("08", table_id)

            for col in amount_cols:
                # 1. Code 20 Validation (scoped to this table_id)
                if row_20:
                    source_rows_items = []
                    computed_20 = 0.0

                    if row_08:
                        computed_20 += row_08.values.get(col, 0.0)
                        source_rows_items.append(row_08)
                        # 20 = 08 + 09 + 10 + 11 + 12 + [13 nếu không phải subtotal] + 14 + 15 + 17
                        for code in ["09", "10", "11", "12"]:
                            for r in by_table(code, table_id):
                                computed_20 += r.values.get(col, 0.0)
                                source_rows_items.append(r)
                        for r in by_table("13", table_id):
                            if not _is_cf20_subtotal_row(r, model):
                                computed_20 += r.values.get(col, 0.0)
                                source_rows_items.append(r)
                        for code in ["14", "15", "17"]:
                            for r in by_table(code, table_id):
                                computed_20 += r.values.get(col, 0.0)
                                source_rows_items.append(r)
                    else:
                        # 20 = 09+10+11+12+[13 nếu không phải subtotal]+14+15+17
                        for code in ["09", "10", "11", "12"]:
                            for r in by_table(code, table_id):
                                computed_20 += r.values.get(col, 0.0)
                                source_rows_items.append(r)
                        for r in by_table("13", table_id):
                            if not _is_cf20_subtotal_row(r, model):
                                computed_20 += r.values.get(col, 0.0)
                                source_rows_items.append(r)
                        for code in ["14", "15", "17"]:
                            for r in by_table(code, table_id):
                                computed_20 += r.values.get(col, 0.0)
                                source_rows_items.append(r)

                    reported_20 = row_20.values.get(col, 0.0)
                    source_rows_items.append(row_20)

                    tolerance = materiality.compute(
                        max(abs(reported_20), abs(computed_20)), table_type
                    )
                    ev = self._make_evidence(
                        f"CF Formula Code 20 [{col}]",
                        expected=reported_20,
                        actual=computed_20,
                        tolerance=tolerance,
                        table_type=table_type,
                        table_id=table_id,
                        source_rows=[r.source_idx for r in source_rows_items],
                        source_cols=[col],
                    )
                    ev.metadata["source_locations"] = [
                        {"table_id": r.table_id, "row_idx": r.source_idx}
                        for r in source_rows_items
                    ]
                    evidence_list.append(ev)

                # 2. Code 30 (scoped to table_id)
                if row_30:
                    computed_30 = 0.0
                    source_rows_items = [row_30]
                    for code in ["21", "22", "23", "24", "25", "26", "27"]:
                        rows = by_table(code, table_id)
                        computed_30 += sum(r.values.get(col, 0.0) for r in rows)
                        source_rows_items.extend(rows)
                    reported_30 = row_30.values.get(col, 0.0)

                    tolerance = materiality.compute(
                        max(abs(reported_30), abs(computed_30)), table_type
                    )
                    ev = self._make_evidence(
                        f"CF Formula Code 30 [{col}]",
                        expected=reported_30,
                        actual=computed_30,
                        tolerance=tolerance,
                        table_type=table_type,
                        table_id=table_id,
                        source_rows=[r.source_idx for r in source_rows_items],
                        source_cols=[col],
                    )
                    ev.metadata["source_locations"] = [
                        {"table_id": r.table_id, "row_idx": r.source_idx}
                        for r in source_rows_items
                    ]
                    evidence_list.append(ev)

                # 3. Code 40 (scoped to table_id)
                if row_40:
                    computed_40 = sum(
                        r.values.get(col, 0.0) for r in by_table("31", table_id)
                    )
                    for code in ["32", "33", "34", "35", "36"]:
                        computed_40 += sum(
                            r.values.get(col, 0.0) for r in by_table(code, table_id)
                        )

                    reported_40 = row_40.values.get(col, 0.0)
                    source_rows_items = [row_40]
                    for code in ["31", "32", "33", "34", "35", "36"]:
                        source_rows_items.extend(by_table(code, table_id))

                    tolerance = materiality.compute(
                        max(abs(reported_40), abs(computed_40)), table_type
                    )
                    ev = self._make_evidence(
                        f"CF Formula Code 40 [{col}]",
                        expected=reported_40,
                        actual=computed_40,
                        tolerance=tolerance,
                        table_type=table_type,
                        table_id=table_id,
                        source_rows=[r.source_idx for r in source_rows_items],
                        source_cols=[col],
                    )
                    ev.metadata["source_locations"] = [
                        {"table_id": r.table_id, "row_idx": r.source_idx}
                        for r in source_rows_items
                    ]
                    evidence_list.append(ev)

                # 4. Code 50 (50 = 20 + 30 + 40; code 20 may be in another CF table)
                if row_50:
                    val_20 = sum(r.values.get(col, 0.0) for r in model.find_code("20"))
                    val_30 = row_30.values.get(col, 0.0) if row_30 else 0.0
                    val_40 = row_40.values.get(col, 0.0) if row_40 else 0.0

                    computed_50 = val_20 + val_30 + val_40
                    reported_50 = row_50.values.get(col, 0.0)

                    source_rows_items = [row_50]
                    source_rows_items.extend(model.find_code("20"))
                    if row_30:
                        source_rows_items.append(row_30)
                    if row_40:
                        source_rows_items.append(row_40)

                    tolerance = materiality.compute(
                        max(abs(reported_50), abs(computed_50)), table_type
                    )
                    ev = self._make_evidence(
                        f"CF Formula Code 50 [{col}]",
                        expected=reported_50,
                        actual=computed_50,
                        tolerance=tolerance,
                        table_type=table_type,
                        table_id=table_id,
                        source_rows=[r.source_idx for r in source_rows_items],
                        source_cols=[col],
                    )
                    ev.metadata["source_locations"] = [
                        {"table_id": r.table_id, "row_idx": r.source_idx}
                        for r in source_rows_items
                    ]
                    evidence_list.append(ev)

                # 5. Code 70 (scoped to table_id). Formula: 70 = 50 + 60 [+ 61 nếu có]
                if row_70:
                    val_50 = row_50.values.get(col, 0.0) if row_50 else 0.0
                    val_60 = sum(
                        r.values.get(col, 0.0) for r in by_table("60", table_id)
                    )
                    rows_61 = by_table("61", table_id)
                    val_61 = sum(r.values.get(col, 0.0) for r in rows_61)

                    computed_70 = val_50 + val_60 + val_61
                    reported_70 = row_70.values.get(col, 0.0)

                    source_rows_items = [row_70]
                    if row_50:
                        source_rows_items.append(row_50)
                    source_rows_items.extend(by_table("60", table_id))
                    if rows_61:
                        source_rows_items.extend(rows_61)

                    tolerance = materiality.compute(
                        max(abs(reported_70), abs(computed_70)), table_type
                    )
                    ev = self._make_evidence(
                        f"CF Formula Code 70 (70 = 50 + 60 [+ 61 nếu có]) [{col}]",
                        expected=reported_70,
                        actual=computed_70,
                        tolerance=tolerance,
                        table_type=table_type,
                        table_id=table_id,
                        source_rows=[r.source_idx for r in source_rows_items],
                        source_cols=[col],
                    )
                    ev.metadata["source_locations"] = [
                        {"table_id": r.table_id, "row_idx": r.source_idx}
                        for r in source_rows_items
                    ]
                    evidence_list.append(ev)

        return evidence_list

    def evaluate(
        self,
        df: pd.DataFrame,
        *,
        materiality: MaterialityEngine,
        table_type: str,
        table_id: str | None = None,
        code_col: str | None = None,
        amount_cols: list[str] | None = None,
        **kwargs,
    ) -> list[ValidationEvidence]:
        # Legacy evaluate is intentionally left blank since AuditGradeValidator calls evaluate_model
        return []
