"""
Income Statement Rules.

Applies standard VAS/IFRS formula assertions based on line item codes.
"""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING

import pandas as pd

from quality_audit.core.evidence import Severity, ValidationEvidence
from quality_audit.core.rules.base_rule import AuditRule
from quality_audit.core.rules.sum_within_tolerance import SumWithinToleranceRule

if TYPE_CHECKING:
    from quality_audit.core.materiality import MaterialityEngine
    from quality_audit.core.model.statement_model_builder import (
        StatementModel,
    )


logger = logging.getLogger(__name__)


class IncomeStatementRules(AuditRule):
    """
    Validates standard Income Statement formulas using item Codes.
    """

    rule_id = "IS_FORMULA_CHECK"
    description = (
        "Kiểm tra các chỉ tiêu tính toán trên Báo cáo Kết quả Hoạt động Kinh doanh"
    )
    severity_default = Severity.MAJOR
    table_types = ["FS_INCOME_STATEMENT"]

    def __init__(self):
        super().__init__()
        self._sum_rule = SumWithinToleranceRule()

    def evaluate_model(
        self, model: StatementModel, *, materiality: MaterialityEngine, **kwargs
    ) -> list[ValidationEvidence]:
        evidence_list: list[ValidationEvidence] = []
        if not model.rows:
            return evidence_list

        table_type = model.statement_type

        # Check for misrouted narrative tables (FS Routing Sanity check)
        if model.is_narrative_statement:
            table_id = model.rows[0].table_id if model.rows else ""
            from quality_audit.core.evidence.validation_evidence import (
                ValidationEvidence,
            )

            return [
                ValidationEvidence.warn_evidence(
                    rule_id=self.rule_id,
                    assertion_text="Income Statement Code Pattern Sanity Check (Narrative)",
                    reason_code="ROUTE_CORRECTION",
                    table_type=table_type,
                    table_id=table_id,
                )._apply_route_correction_metadata()
            ]

        # Collect amount_cols from any row which has them
        amount_cols = set()
        for r in model.rows:
            amount_cols.update(r.values.keys())
        amount_cols = list(amount_cols)

        row_20 = next(iter(model.find_code("20")), None)
        row_30 = next(iter(model.find_code("30")), None)
        row_40 = next(iter(model.find_code("40")), None)
        row_50 = next(iter(model.find_code("50")), None)
        row_60 = next(iter(model.find_code("60")), None)
        next(iter(model.find_code("70")), None)

        # Scoped code matching for 24
        val_24_rows = [
            r
            for r in model.find_code("24")
            if "associate" in r.label.lower()
            or "share" in r.label.lower()
            or "liên doanh" in r.label.lower()
            or "liên kết" in r.label.lower()
        ]
        if not val_24_rows:
            val_24_rows = (
                model.find_label("share of")
                or model.find_label("liên doanh")
                or model.find_code("24")
            )
        row_24 = val_24_rows[0] if val_24_rows else None

        for col in amount_cols:
            # 1. Code 20: CJ (no 10) 20 = 01 - 02 - 11; CP (has 10) 20 = 10 - 11
            if row_20:
                rows_10 = list(model.find_code("10"))
                val_11 = sum(r.values.get(col, 0.0) for r in model.find_code("11"))

                if rows_10:
                    val_10 = sum(r.values.get(col, 0.0) for r in rows_10)
                    computed_20 = val_10 - val_11
                    source_rows_items = [row_20]
                    source_rows_items.extend(rows_10)
                    source_rows_items.extend(model.find_code("11"))
                else:
                    val_01 = sum(r.values.get(col, 0.0) for r in model.find_code("01"))
                    val_02 = sum(r.values.get(col, 0.0) for r in model.find_code("02"))
                    computed_20 = val_01 - val_02 - val_11
                    source_rows_items = [row_20]
                    for code in ["01", "02", "11"]:
                        source_rows_items.extend(model.find_code(code))

                reported_20 = row_20.values.get(col, 0.0)

                tolerance = materiality.compute(
                    max(abs(reported_20), abs(computed_20)), table_type
                )
                ev = self._make_evidence(
                    f"IS Formula Code 20 [{col}]",
                    expected=reported_20,
                    actual=computed_20,
                    tolerance=tolerance,
                    table_type=table_type,
                    table_id=row_20.table_id,
                    source_rows=[r.source_idx for r in source_rows_items],
                    source_cols=[col],
                )
                ev.metadata["source_locations"] = [
                    {"table_id": r.table_id, "row_idx": r.source_idx}
                    for r in source_rows_items
                ]
                evidence_list.append(ev)

            # 2. Code 30: 20 + 21 - 22 + 24 - (25 + 26)
            if row_30:
                val_20 = row_20.values.get(col, 0.0) if row_20 else 0.0
                val_21 = sum(r.values.get(col, 0.0) for r in model.find_code("21"))
                val_22 = sum(r.values.get(col, 0.0) for r in model.find_code("22"))
                val_24 = row_24.values.get(col, 0.0) if row_24 else 0.0
                val_25 = sum(r.values.get(col, 0.0) for r in model.find_code("25"))
                val_26 = sum(r.values.get(col, 0.0) for r in model.find_code("26"))

                computed_30 = val_20 + (val_21 - val_22) + val_24 - (val_25 + val_26)
                reported_30 = row_30.values.get(col, 0.0)

                source_rows_items = [row_30]
                if row_20:
                    source_rows_items.append(row_20)
                if row_24:
                    source_rows_items.append(row_24)
                for code in ["21", "22", "25", "26"]:
                    source_rows_items.extend(model.find_code(code))

                tolerance = materiality.compute(
                    max(abs(reported_30), abs(computed_30)), table_type
                )
                ev = self._make_evidence(
                    f"IS Formula Code 30 [{col}]",
                    expected=reported_30,
                    actual=computed_30,
                    tolerance=tolerance,
                    table_type=table_type,
                    table_id=row_30.table_id,
                    source_rows=[r.source_idx for r in source_rows_items],
                    source_cols=[col],
                )
                ev.metadata["source_locations"] = [
                    {"table_id": r.table_id, "row_idx": r.source_idx}
                    for r in source_rows_items
                ]
                evidence_list.append(ev)

            # 3. Code 40: 31 - 32
            if row_40:
                val_31 = sum(r.values.get(col, 0.0) for r in model.find_code("31"))
                val_32 = sum(r.values.get(col, 0.0) for r in model.find_code("32"))

                computed_40 = val_31 - val_32
                reported_40 = row_40.values.get(col, 0.0)

                source_rows_items = [row_40]
                for code in ["31", "32"]:
                    source_rows_items.extend(model.find_code(code))

                tolerance = materiality.compute(
                    max(abs(reported_40), abs(computed_40)), table_type
                )
                ev = self._make_evidence(
                    f"IS Formula Code 40 [{col}]",
                    expected=reported_40,
                    actual=computed_40,
                    tolerance=tolerance,
                    table_type=table_type,
                    table_id=row_40.table_id,
                    source_rows=[r.source_idx for r in source_rows_items],
                    source_cols=[col],
                )
                ev.metadata["source_locations"] = [
                    {"table_id": r.table_id, "row_idx": r.source_idx}
                    for r in source_rows_items
                ]
                evidence_list.append(ev)

            # 4. Code 50: 30 + 40
            if row_50:
                val_30 = row_30.values.get(col, 0.0) if row_30 else 0.0
                val_40 = row_40.values.get(col, 0.0) if row_40 else 0.0

                computed_50 = val_30 + val_40
                reported_50 = row_50.values.get(col, 0.0)

                source_rows_items = [r for r in [row_30, row_40, row_50] if r]

                tolerance = materiality.compute(
                    max(abs(reported_50), abs(computed_50)), table_type
                )
                ev = self._make_evidence(
                    f"IS Formula Code 50 [{col}]",
                    expected=reported_50,
                    actual=computed_50,
                    tolerance=tolerance,
                    table_type=table_type,
                    table_id=row_50.table_id,
                    source_rows=[r.source_idx for r in source_rows_items],
                    source_cols=[col],
                )
                ev.metadata["source_locations"] = [
                    {"table_id": r.table_id, "row_idx": r.source_idx}
                    for r in source_rows_items
                ]
                evidence_list.append(ev)

            # 5. Code 60: 50 - 51 - 52
            if row_60:
                val_50 = row_50.values.get(col, 0.0) if row_50 else 0.0
                val_51 = sum(r.values.get(col, 0.0) for r in model.find_code("51"))
                val_52 = sum(r.values.get(col, 0.0) for r in model.find_code("52"))

                computed_60 = val_50 - val_51 - val_52
                reported_60 = row_60.values.get(col, 0.0)

                source_rows_items = [row_60]
                if row_50:
                    source_rows_items.append(row_50)
                for code in ["51", "52"]:
                    source_rows_items.extend(model.find_code(code))

                tolerance = materiality.compute(
                    max(abs(reported_60), abs(computed_60)), table_type
                )
                ev = self._make_evidence(
                    f"IS Formula Code 60 [{col}]",
                    expected=reported_60,
                    actual=computed_60,
                    tolerance=tolerance,
                    table_type=table_type,
                    table_id=row_60.table_id,
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
        # Legacy evaluate left blank
        return []
