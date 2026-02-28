"""
Cash Flow Rules.

Applies standard VAS/IFRS formula assertions for Statement of Cash Flows
based on line item codes.
"""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING, Dict, List, Optional

import pandas as pd

from quality_audit.core.evidence import Severity, ValidationEvidence
from quality_audit.core.rules.base_rule import AuditRule

if TYPE_CHECKING:
    from quality_audit.core.materiality import MaterialityEngine


logger = logging.getLogger(__name__)


class CashFlowRules(AuditRule):
    """
    Validates standard Cash Flow formulas using item Codes.
    """

    rule_id = "CF_FORMULA_CHECK"
    description = "Kiểm tra các chỉ tiêu tính toán trên Lưu chuyển tiền tệ"
    severity_default = Severity.MAJOR
    table_types = ["FS_CASH_FLOW"]

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
        Evaluate CF formulas.

        Common VAS CF formulas:
        - 20 = sum(01..19) (Operating Cash Flow)
        - 30 = sum(21..29) (Investing Cash Flow)
        - 40 = sum(31..39) (Financing Cash Flow)
        - 50 = 20 + 30 + 40 (Net Cash Flow)
        - 70 = 50 + 60 + 61 (Closing Cash = Net + Opening + FX impact)
        """
        evidence_list: List[ValidationEvidence] = []
        if not code_col or not amount_cols or code_col not in df.columns:
            return evidence_list

        code_to_idx: Dict[str, int] = {}
        for idx, row in df.iterrows():
            code_val = str(row[code_col]).strip()
            if code_val.isdigit() and len(code_val) == 1:
                code_val = f"0{code_val}"
            if code_val:
                code_to_idx[code_val] = idx

        # target code -> list of codes to sum
        sum_formulas = {
            "20": [f"{i:02d}" for i in range(1, 20)],
            "30": [f"{i:02d}" for i in range(21, 30)],
            "40": [f"{i:02d}" for i in range(31, 40)],
        }

        # target code -> exact formula
        exact_formulas = [
            {"target": "50", "add": ["20", "30", "40"], "sub": []},
            {"target": "70", "add": ["50", "60", "61"], "sub": []},
        ]

        # 1. Evaluate sum formulas
        for target_code, add_codes in sum_formulas.items():
            if target_code not in code_to_idx:
                continue

            target_idx = code_to_idx[target_code]
            for col in amount_cols:
                if col not in df.columns:
                    continue

                actual_computed = 0.0
                source_rows = []
                valid_components = False

                for code in add_codes:
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

                if not valid_components:
                    continue

                try:
                    reported_val = float(df.iloc[target_idx][col])
                    if pd.isna(reported_val):
                        continue
                except (ValueError, TypeError):
                    continue

                source_rows.append(target_idx)
                magnitude = max(abs(reported_val), abs(actual_computed))
                tolerance = materiality.compute(magnitude, table_type)

                assertion_text = f"CF Sum Code {target_code} [{col}]"

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
                evidence.metadata["target"] = target_code
                evidence_list.append(evidence)

        # 2. Evaluate exact formulas
        for formula in exact_formulas:
            target_code = formula["target"]
            if target_code not in code_to_idx:
                continue

            target_idx = code_to_idx[target_code]
            for col in amount_cols:
                if col not in df.columns:
                    continue

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

                if not valid_components:
                    continue

                try:
                    reported_val = float(df.iloc[target_idx][col])
                    if pd.isna(reported_val):
                        continue
                except (ValueError, TypeError):
                    continue

                source_rows.append(target_idx)
                magnitude = max(abs(reported_val), abs(actual_computed))
                tolerance = materiality.compute(magnitude, table_type)

                assertion_text = f"CF Formula Code {target_code} [{col}]"

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
