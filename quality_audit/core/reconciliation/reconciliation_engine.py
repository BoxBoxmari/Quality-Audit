"""
Cross-statement reconciliation engine.
Orchestrates high-level integrity checks across Financial Statements.
"""

from __future__ import annotations

import logging

from quality_audit.core.evidence import Severity, ValidationEvidence
from quality_audit.core.materiality import MaterialityEngine
from quality_audit.core.model.financial_model import FinancialModel

logger = logging.getLogger(__name__)


class ReconciliationEngine:
    """Orchestrates cross-statement integrity checks."""

    def __init__(self, materiality_engine: MaterialityEngine) -> None:
        self.materiality = materiality_engine

    def reconcile(self, model: FinancialModel) -> list[ValidationEvidence]:
        """Perform all configured cross-checks on the model."""
        evidence_list = []
        evidence_list.extend(self._reconcile_cf_bs_cash(model))
        evidence_list.extend(self._reconcile_is_equity(model))
        evidence_list.extend(self._reconcile_notes_to_fs(model))
        return evidence_list

    def _create_evidence(
        self,
        rule_id: str,
        assertion: str,
        expected: float,
        actual: float,
        col_name: str,
    ) -> ValidationEvidence:
        """Helper to evaluate and create evidence."""
        magnitude = max(abs(expected), abs(actual))
        tolerance = self.materiality.compute(magnitude, "RECONCILIATION")
        variance = abs(expected - actual)

        if variance <= tolerance:
            return ValidationEvidence.pass_evidence(
                rule_id=rule_id,
                assertion_text=assertion,
                expected=expected,
                actual=actual,
                tolerance=tolerance,
            )
        else:
            return ValidationEvidence.fail_evidence(
                rule_id=rule_id,
                assertion_text=assertion,
                expected=expected,
                actual=actual,
                tolerance=tolerance,
                severity=Severity.MAJOR,
            )

    def _reconcile_cf_bs_cash(self, model: FinancialModel) -> list[ValidationEvidence]:
        """Verify Ending Cash on CF == Cash on BS."""
        results = []
        for col_idx, col_name in [(0, "Current Period"), (1, "Previous Period")]:
            # CF Cash End (code 70)
            cf_cash = model.get_line_item("FS_CASH_FLOW", "70", col_idx=col_idx)
            # BS Cash Total (code 110)
            bs_cash = model.get_line_item("FS_BALANCE_SHEET", "110", col_idx=col_idx)

            if cf_cash is not None and bs_cash is not None:
                results.append(
                    self._create_evidence(
                        rule_id="RECON_CF_VS_BS_CASH",
                        assertion=f"[{col_name}] Ending Cash CF(70) == Cash BS(110)",
                        expected=bs_cash,
                        actual=cf_cash,
                        col_name=col_name,
                    )
                )
        return results

    def _reconcile_is_equity(self, model: FinancialModel) -> list[ValidationEvidence]:
        """Net profit from IS matches Equity Changes."""
        results = []
        for col_idx, col_name in [(0, "Current Period"), (1, "Previous Period")]:
            # IS Net Profit (code 60)
            is_profit = model.get_line_item(
                "FS_INCOME_STATEMENT", "60", col_idx=col_idx
            )

            # Simple check against an assumed equity code (e.g. 50 in some formats)
            # If Statement of Equity is populated and has code 50:
            eq_profit = model.get_line_item("FS_EQUITY", "50", col_idx=col_idx)

            if is_profit is not None and eq_profit is not None:
                results.append(
                    self._create_evidence(
                        rule_id="RECON_IS_VS_EQUITY_PROFIT",
                        assertion=f"[{col_name}] Net Profit IS(60) == Profit Equity(50)",
                        expected=is_profit,
                        actual=eq_profit,
                        col_name=col_name,
                    )
                )
        return results

    def _reconcile_notes_to_fs(self, model: FinancialModel) -> list[ValidationEvidence]:
        """Verify Note breakdown totals match parent FS line items."""
        # Generic placeholder for reconciling note totals to FS.
        # e.g., if a NOTE table has code "110", match it to FS_BALANCE_SHEET "110".
        results = []
        return results
