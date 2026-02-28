"""
AuditGradeValidator for orchestrating rules per table and model.
"""

from __future__ import annotations

import logging
from typing import Any

from quality_audit.core.evidence import ValidationEvidence
from quality_audit.core.materiality import MaterialityEngine
from quality_audit.core.model.financial_model import FinancialModel
from quality_audit.core.reconciliation.reconciliation_engine import ReconciliationEngine
from quality_audit.core.rules.rule_registry import RuleRegistry

logger = logging.getLogger(__name__)


class AuditGradeValidator:
    """Orchestrates rule evaluation for single tables and full models."""

    def __init__(
        self,
        registry: RuleRegistry,
        materiality: MaterialityEngine,
    ) -> None:
        self.registry = registry
        self.materiality = materiality
        self.reconciler = ReconciliationEngine(self.materiality)

    def validate_table(self, table_info: dict[str, Any]) -> list[ValidationEvidence]:
        """
        Apply all registered rules to a single table.

        Args:
            table_info: Dict containing 'df', 'table_type', 'code_col', 'amount_cols'.

        Returns:
            List of ValidationEvidence records.
        """
        table_type = table_info.get("table_type")
        df = table_info.get("df")

        if not table_type or df is None:
            logger.warning("Invalid table_info passed to validate_table.")
            return []

        rules = self.registry.resolve(table_type)
        evidence_list = []

        code_col = table_info.get("code_col")
        amount_cols = table_info.get("amount_cols", [])
        table_id = table_info.get("table_id")

        for rule in rules:
            try:
                rule_evidence = rule.evaluate(
                    df=df,
                    materiality=self.materiality,
                    table_type=table_type,
                    table_id=table_id,
                    code_col=code_col,
                    amount_cols=amount_cols,
                )
                evidence_list.extend(rule_evidence)
            except Exception as e:
                logger.exception(
                    "Error executing rule %s on table %s: %s",
                    rule.rule_id,
                    table_type,
                    e,
                )

        return evidence_list

    def validate_model(self, model: FinancialModel) -> list[ValidationEvidence]:
        """
        Analyze a complete FinancialModel including cross-statement checks.

        Returns:
            List of all ValidationEvidence from the entire model.
        """
        all_evidence = []

        # Validate each table individually
        for table_info in model.income_statements:
            all_evidence.extend(self.validate_table(table_info))

        for table_info in model.balance_sheets:
            all_evidence.extend(self.validate_table(table_info))

        for table_info in model.cash_flows:
            all_evidence.extend(self.validate_table(table_info))

        for table_info in model.equity_changes:
            all_evidence.extend(self.validate_table(table_info))

        for table_info in model.notes:
            all_evidence.extend(self.validate_table(table_info))

        # Perform cross-statement reconciliations
        recon_evidence = self.reconciler.reconcile(model)
        all_evidence.extend(recon_evidence)

        return all_evidence
