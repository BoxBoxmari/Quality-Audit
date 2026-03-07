"""
CrossCheckRule for cross-statement validations.

Validates that a specific value in the current table matches
a reference value from another statement, within tolerance.
"""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING

import pandas as pd

from quality_audit.core.evidence import Severity, ValidationEvidence
from quality_audit.core.rules.base_rule import AuditRule

if TYPE_CHECKING:
    from quality_audit.core.materiality import MaterialityEngine


logger = logging.getLogger(__name__)


class CrossCheckRule(AuditRule):
    """
    Validates a value against an external reference (e.g. BS vs CF).
    """

    rule_id = "CROSS_CHECK_MATCH"
    description = "Kiểm tra đối chiếu với các Bảng/Thuyết minh liên quan"
    severity_default = Severity.MAJOR

    def evaluate(
        self,
        df: pd.DataFrame,
        *,
        materiality: MaterialityEngine,
        table_type: str,
        table_id: str | None = None,
        code_col: str | None = None,
        amount_cols: list[str] | None = None,
        verify_items: list[dict] | None = None,
        **kwargs,
    ) -> list[ValidationEvidence]:
        """
        Evaluate cross-check matches.

        Args:
            verify_items: List of specification dicts:
                [
                    {
                        "row_idx": 5,
                        "col_name": "Năm nay",
                        "expected_value": 15000.0,
                        "reference_name": "BS_Cash_Closing"
                    }
                ]
        """
        evidence_list: list[ValidationEvidence] = []

        if not verify_items:
            logger.debug("CrossCheckRule: no items to verify")
            return evidence_list

        for item in verify_items:
            r = item.get("row_idx")
            c = item.get("col_name")
            expected_val = item.get("expected_value")
            ref_name = item.get("reference_name", "Unknown Reference")

            if r is None or c is None or expected_val is None:
                continue
            if c not in df.columns:
                continue

            try:
                actual_val = float(df.iloc[r][c])
            except (ValueError, TypeError, IndexError):
                continue

            magnitude = max(abs(expected_val), abs(actual_val))
            tolerance = materiality.compute(magnitude, table_type)

            assertion_text = f"Cross-check [{ref_name}] == Actual [{c}]"

            evidence = self._make_evidence(
                assertion_text=assertion_text,
                expected=expected_val,
                actual=actual_val,
                tolerance=tolerance,
                table_type=table_type,
                table_id=table_id,
                source_rows=[r],
                source_cols=[c],
            )

            # Enrich the evidence metadata with the reference name
            evidence.metadata["reference_name"] = ref_name
            evidence_list.append(evidence)

        return evidence_list
