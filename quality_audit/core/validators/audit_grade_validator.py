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

        total_row_idx = table_info.get("total_row_idx")
        detail_rows = table_info.get("detail_rows")

        for rule in rules:
            try:
                rule_evidence = rule.evaluate(
                    df=df,
                    materiality=self.materiality,
                    table_type=table_type,
                    table_id=table_id,
                    code_col=code_col,
                    amount_cols=amount_cols,
                    total_row_idx=total_row_idx,
                    detail_rows=detail_rows,
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
        from quality_audit.core.model.statement_model_builder import (
            StatementModelBuilder,
        )

        builder = StatementModelBuilder()
        all_evidence = []

        # Process standard statements
        for _, statement_tables in [
            ("FS_INCOME_STATEMENT", model.income_statements),
            ("FS_BALANCE_SHEET", model.balance_sheets),
            ("FS_CASH_FLOW", model.cash_flows),
            ("FS_EQUITY_CHANGES", model.equity_changes),
        ]:
            if not statement_tables:
                continue

            # Group tables by their specific table_type
            table_types = list(
                {t.get("table_type") for t in statement_tables if t.get("table_type")}
            )

            for t_type in table_types:
                rules = self.registry.resolve(t_type)
                if not rules:
                    continue

                relevant_tables = [
                    t for t in statement_tables if t.get("table_type") == t_type
                ]
                statement_model = builder.build(relevant_tables, t_type)

                for rule in rules:
                    # If the rule overrides evaluate_model, use it
                    if (
                        type(rule).evaluate_model
                        is not __import__(
                            "quality_audit.core.rules.base_rule", fromlist=["AuditRule"]
                        ).AuditRule.evaluate_model
                    ):
                        try:
                            logger.debug(
                                "Running statement-level rule %s", rule.rule_id
                            )
                            rule_evidence = rule.evaluate_model(
                                model=statement_model, materiality=self.materiality
                            )
                            all_evidence.extend(rule_evidence)
                        except Exception as e:
                            logger.exception(
                                "Error executing statement-level rule %s: %s",
                                rule.rule_id,
                                e,
                            )
                    else:
                        # Fallback to legacy evaluate with individual table slices
                        for t in relevant_tables:
                            if t.get("df") is None:
                                continue
                            try:
                                rule_evidence = rule.evaluate(
                                    df=t["df"],
                                    materiality=self.materiality,
                                    table_type=t.get("table_type"),
                                    table_id=t.get("table_id"),
                                    code_col=t.get("code_col"),
                                    amount_cols=t.get("amount_cols", []),
                                    total_row_idx=t.get("total_row_idx"),
                                    detail_rows=t.get("detail_rows"),
                                )
                                all_evidence.extend(rule_evidence)
                            except Exception as e:
                                logger.exception(
                                    "Error executing legacy rule %s on table %s: %s",
                                    rule.rule_id,
                                    t.get("table_id"),
                                    e,
                                )

        # Notes are still validated individually since they are distinct
        for table_info in model.notes:
            all_evidence.extend(self.validate_table(table_info))

        # Perform cross-statement reconciliations
        recon_evidence = self.reconciler.reconcile(model)
        all_evidence.extend(recon_evidence)

        return all_evidence
