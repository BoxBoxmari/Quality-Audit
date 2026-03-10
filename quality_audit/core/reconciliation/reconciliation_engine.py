"""
Cross-statement reconciliation engine.
Orchestrates high-level integrity checks across Financial Statements.
"""

from __future__ import annotations

import logging

import pandas as pd

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

    def _is_note_4_cash(self, table_id: str, heading: str) -> bool:
        """True if table_id or heading suggest Note 4 Cash (cash/tiền and 4)."""
        tid = (table_id or "").strip().lower()
        h = (heading or "").strip().lower()
        has_4 = "4" in (table_id or "") or "4" in (heading or "")
        has_cash = "cash" in h or "tiền" in h or "cash" in tid
        return bool(has_4 and has_cash)

    def _reconcile_notes_to_fs(self, model: FinancialModel) -> list[ValidationEvidence]:
        """Verify Note 4 Cash total ties to BS Cash (code 110)."""
        results = []
        for note in model.notes:
            table_id = note.get("table_id") or ""
            heading = note.get("heading") or ""
            if not self._is_note_4_cash(table_id, heading):
                continue
            df = note.get("df")
            amount_cols = note.get("amount_cols") or []
            if df is None or not amount_cols:
                continue
            col = amount_cols[0]
            if col not in df.columns:
                continue
            try:
                note_total = float(pd.to_numeric(df[col], errors="coerce").sum())
            except (TypeError, ValueError):
                continue
            if pd.isna(note_total):
                continue
            bs_cash = model.get_line_item("FS_BALANCE_SHEET", "110", col_idx=0)
            if bs_cash is None:
                continue
            magnitude = max(abs(note_total), abs(bs_cash))
            tolerance = self.materiality.compute(magnitude, "RECONCILIATION")
            variance = abs(note_total - bs_cash)
            assertion = "Note 4 Cash total ties to BS Cash (110)"
            if variance <= tolerance:
                results.append(
                    ValidationEvidence.pass_evidence(
                        rule_id="RECON_NOTE_4_CASH_VS_BS",
                        assertion_text=assertion,
                        expected=bs_cash,
                        actual=note_total,
                        tolerance=tolerance,
                        table_id=table_id or None,
                    )
                )
            else:
                results.append(
                    ValidationEvidence.fail_evidence(
                        rule_id="RECON_NOTE_4_CASH_VS_BS",
                        assertion_text=assertion,
                        expected=bs_cash,
                        actual=note_total,
                        tolerance=tolerance,
                        severity=Severity.MAJOR,
                        table_id=table_id or None,
                    )
                )
        return results
