"""
Balance Sheet Rules.

Applies standard VAS/IFRS formula assertions for Balance Sheet
based on line item codes.
"""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING, cast

import pandas as pd

from quality_audit.core.evidence import Severity, ValidationEvidence
from quality_audit.core.rules.base_rule import AuditRule

if TYPE_CHECKING:
    from quality_audit.core.materiality import MaterialityEngine


logger = logging.getLogger(__name__)


class BalanceSheetRules(AuditRule):
    """
    Validates standard Balance Sheet formulas using item Codes.
    """

    rule_id = "BS_FORMULA_CHECK"
    description = "Kiểm tra phương trình kế toán cơ bản trên Bảng Cân đối Kế toán"
    severity_default = Severity.MAJOR
    table_types = ["FS_BALANCE_SHEET"]

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
        """
        Evaluate BS formulas.

        Common VAS BS formulas:
        - 270 = 100 + 200 (Total Assets = Current + Non-current)
        - 440 = 300 + 400 (Total Resources = Liabilities + Equity)
        - 270 = 440 (Assets = Resources)
        """
        evidence_list: list[ValidationEvidence] = []
        if not code_col or not amount_cols or code_col not in df.columns:
            return evidence_list

        # Run FS Routing Sanity check by building a temporary StatementModel
        from quality_audit.core.model.statement_model_builder import (
            StatementModelBuilder,
        )

        temp_model = StatementModelBuilder().build(
            [
                {
                    "df": df,
                    "table_id": table_id,
                    "table_type": table_type,
                    "code_col": code_col,
                    "amount_cols": amount_cols,
                }
            ],
            table_type,
        )
        if temp_model.is_narrative_statement:
            from quality_audit.core.evidence.validation_evidence import (
                ValidationEvidence,
            )

            return [
                ValidationEvidence.warn_evidence(
                    rule_id=self.rule_id,
                    assertion_text="Balance Sheet Code Pattern Sanity Check (Narrative)",
                    reason_code="ROUTE_CORRECTION",
                    table_type=table_type,
                    table_id=table_id or "",
                )._apply_route_correction_metadata()
            ]

        code_to_idx: dict[str, int] = {}
        for idx, row in df.iterrows():
            code_val = str(row[code_col]).strip()
            if code_val:
                code_to_idx[code_val] = idx

        logger.info(
            "[BS Rules] table_id=%s code_col=%r amount_cols=%s code_to_idx ALL keys=%s",
            table_id,
            code_col,
            amount_cols,
            list(code_to_idx.keys()),
        )

        formulas: list[dict[str, object]] = [
            {"target": "270", "add": ["100", "200"], "sub": []},
            {"target": "440", "add": ["300", "400"], "sub": []},
            {"target": "270", "add": ["440"], "sub": []},
        ]

        for formula in formulas:
            target_code = str(formula["target"])
            if target_code not in code_to_idx:
                continue

            target_idx = code_to_idx[target_code]
            for col in amount_cols:
                if col not in df.columns:
                    continue

                actual_computed = 0.0
                source_rows = []
                valid_components = False

                add_codes = cast(list[str], formula["add"])
                for code in add_codes:
                    if code in code_to_idx:
                        r = code_to_idx[code]
                        v = self._parse_float(df.iloc[r][col])
                        if not pd.isna(v):
                            actual_computed += v
                            source_rows.append(r)
                            valid_components = True

                if not valid_components:
                    continue

                reported_val = self._parse_float(df.iloc[target_idx][col])
                if pd.isna(reported_val):
                    continue

                source_rows.append(target_idx)
                magnitude = max(abs(reported_val), abs(actual_computed))
                tolerance = materiality.compute(magnitude, table_type)

                # Special description for Assets = Liabilities + Equity
                if target_code == "270" and "440" in add_codes:
                    assertion_text = f"Tài sản = Nguồn vốn [{col}]"
                else:
                    assertion_text = f"BS Formula Code {target_code} [{col}]"

                evidence = self._make_evidence(
                    assertion_text=assertion_text,
                    expected=reported_val,
                    actual=actual_computed,
                    tolerance=tolerance,
                    table_type=table_type,
                    table_id=table_id,
                    source_rows=source_rows,
                    source_cols=[col],
                )
                evidence.metadata["formula"] = formula
                evidence_list.append(evidence)

        return evidence_list
