"""
Income Statement Rules.

Applies standard VAS/IFRS formula assertions based on line item codes.
"""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING, Dict, List, Optional

import pandas as pd

from quality_audit.core.evidence import Severity, ValidationEvidence
from quality_audit.core.rules.base_rule import AuditRule
from quality_audit.core.rules.sum_within_tolerance import SumWithinToleranceRule

if TYPE_CHECKING:
    from quality_audit.core.materiality import MaterialityEngine


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

    def evaluate(
        self,
        df: pd.DataFrame,
        *,
        materiality: MaterialityEngine,
        table_type: str,
        table_id: Optional[str] = None,
        code_col: Optional[str] = None,
        amount_cols: Optional[List[str]] = None,
        **kwargs,
    ) -> List[ValidationEvidence]:
        """
        Evaluate IS formulas.

        Common VAS formulas:
        - 20 = 01 - 02 - 11 (Revenue - Deductions - COGS)
        - 30 = 20 + 21 - 22 - 25 - 26 (Gross + Fin Rev - Fin Exp - Selling - Admin)
        - 50 = 30 + 40 (Operating Profit + Other Profit)
        - 60 = 50 + 31 - 32 (or simply Accounting Profit before Tax)
        - 70 = 60 - 51 - 52 (Net Profit)
        """
        evidence_list: List[ValidationEvidence] = []
        if not code_col or not amount_cols or code_col not in df.columns:
            return evidence_list

        # Map codes to row indices
        code_to_idx: Dict[str, int] = {}
        for idx, row in df.iterrows():
            code_val = str(row[code_col]).strip()
            # Normalize single digits (e.g. "1" -> "01")
            if code_val.isdigit() and len(code_val) == 1:
                code_val = f"0{code_val}"
            if code_val:
                code_to_idx[code_val] = idx

        formulas = [
            {"target": "20", "add": ["01"], "sub": ["02", "11"]},
            {"target": "30", "add": ["20", "21"], "sub": ["22", "24", "25", "26"]},
            {"target": "40", "add": ["31"], "sub": ["32"]},
            {"target": "50", "add": ["30", "40"], "sub": []},
            {"target": "60", "add": ["50"], "sub": []},
            {"target": "70", "add": ["60"], "sub": ["51", "52"]},
        ]

        for formula in formulas:
            target_code = formula["target"]
            if target_code not in code_to_idx:
                continue

            target_idx = code_to_idx[target_code]

            for col in amount_cols:
                if col not in df.columns:
                    continue

                # Compute actual from formula components
                actual_computed = 0.0
                source_rows = []
                valid_components = False

                for code in formula["add"]:
                    if code in code_to_idx:
                        r = code_to_idx[code]
                        try:
                            v = float(df.iloc[r][col])
                            if not pd.isna(v):
                                actual_computed += v
                                source_rows.append(r)
                                valid_components = True
                        except (ValueError, TypeError):
                            pass

                for code in formula["sub"]:
                    if code in code_to_idx:
                        r = code_to_idx[code]
                        try:
                            v = float(df.iloc[r][col])
                            if not pd.isna(v):
                                actual_computed -= v
                                source_rows.append(r)
                                valid_components = True
                        except (ValueError, TypeError):
                            pass

                if not valid_components:
                    continue

                # Get the reported target value
                try:
                    reported_val = float(df.iloc[target_idx][col])
                    if pd.isna(reported_val):
                        continue
                except (ValueError, TypeError):
                    continue

                source_rows.append(target_idx)
                magnitude = max(abs(reported_val), abs(actual_computed))
                tolerance = materiality.compute(magnitude, table_type)

                assertion_text = f"IS Formula Code {target_code} [{col}]"

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
