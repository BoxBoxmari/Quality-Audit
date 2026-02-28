"""
Balance Sheet Rules.

Applies standard VAS/IFRS formula assertions for Balance Sheet
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
        table_id: Optional[str] = None,
        code_col: Optional[str] = None,
        amount_cols: Optional[List[str]] = None,
        **kwargs,
    ) -> List[ValidationEvidence]:
        """
        Evaluate BS formulas.

        Common VAS BS formulas:
        - 270 = 100 + 200 (Total Assets = Current + Non-current)
        - 440 = 300 + 400 (Total Resources = Liabilities + Equity)
        - 270 = 440 (Assets = Resources)
        """
        evidence_list: List[ValidationEvidence] = []
        if not code_col or not amount_cols or code_col not in df.columns:
            return evidence_list

        code_to_idx: Dict[str, int] = {}
        for idx, row in df.iterrows():
            code_val = str(row[code_col]).strip()
            if code_val:
                code_to_idx[code_val] = idx

        formulas = [
            {"target": "270", "add": ["100", "200"], "sub": []},
            {"target": "440", "add": ["300", "400"], "sub": []},
            {"target": "270", "add": ["440"], "sub": []},
        ]

        for formula in formulas:
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

                # Special description for Assets = Liabilities + Equity
                if target_code == "270" and "440" in formula["add"]:
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
