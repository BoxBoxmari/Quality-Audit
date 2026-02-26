"""
Validator factory for creating appropriate validators based on table type.
"""

import logging
from typing import Any, Dict, Optional, Tuple

import pandas as pd

from quality_audit.config.feature_flags import FEATURE_FLAGS, get_feature_flags
from quality_audit.utils.numeric_utils import compute_numeric_evidence_score

from ..cache_manager import AuditContext
from ..routing.table_type_classifier import TableType, TableTypeClassifier
from .balance_sheet_validator import BalanceSheetValidator

# Import here to avoid circular imports
from .base_validator import BaseValidator
from .cash_flow_validator import CashFlowValidator
from .equity_validator import EquityValidator
from .generic_validator import GenericTableValidator
from .income_statement_validator import IncomeStatementValidator
from .tax_validator import TaxValidator

logger = logging.getLogger(__name__)


class ValidatorFactory:
    """Factory for creating table validators based on content analysis."""

    @staticmethod
    def get_validator(
        table: pd.DataFrame,
        heading: Optional[str],
        context: Optional[AuditContext] = None,
        table_context: Optional[Dict[str, Any]] = None,
    ) -> Tuple[Optional[BaseValidator], Optional[str]]:
        """
        Determine appropriate validator based on table content and heading.

        This replicates the routing logic from the original check_table_total() function
        (lines 1179-1191 in legacy Quality Audit.py).

        Args:
            table: DataFrame containing table data
            heading: Table heading text
            context: Optional audit context to pass to validator
            table_context: Optional per-table metadata (e.g. heading_confidence from word_reader)

        Returns:
            Tuple[Optional[BaseValidator], Optional[str]]: A tuple of (validator, skip_reason).
            - validator: Appropriate validator instance, or None if table should be skipped
            - skip_reason: None if no skip, or a rule_id string like "SKIPPED_FOOTER_SIGNATURE"
              or "SKIPPED_NO_NUMERIC_EVIDENCE" indicating why the table was skipped
        """
        # Check for SKIPPED tables (footer/signature) before classification
        if (
            FEATURE_FLAGS.get("skip_footer_signature_tables", True)
            and heading
            and heading.strip().upper().startswith("SKIPPED_")
        ):
            logger.info("Table skipped: %s, reason=footer_signature", heading)
            return (None, "SKIPPED_FOOTER_SIGNATURE")

        # Use TableTypeClassifier for intelligent routing
        classifier = TableTypeClassifier()
        heading_confidence = (
            table_context.get("heading_confidence") if table_context else None
        )
        result = classifier.classify(
            table, heading, heading_confidence=heading_confidence
        )

        # Store classification result context for observability (Phase 0: classifier metadata)
        if context and result.context:
            result.context["classifier_primary_type"] = result.table_type.value
            result.context["classifier_confidence"] = result.confidence
            context.set_last_classification_context(result.context)

        if result.table_type == TableType.FS_BALANCE_SHEET:
            flags = get_feature_flags()
            gating_enabled = flags.get("routing_balance_sheet_gating_enabled", True)
            if gating_enabled:
                evidence = compute_numeric_evidence_score(table)
                score = evidence.get("numeric_evidence_score", 0.0)
                threshold = float(
                    flags.get("routing_balance_sheet_numeric_threshold", 0.25)
                )
                policy = flags.get(
                    "routing_balance_sheet_gating_policy", "downgrade_to_generic"
                )
                table_id = (result.context or {}).get("table_id") or (
                    table_context or {}
                ).get("table_id")
                if score < threshold:
                    logger.info(
                        "BalanceSheet routing downgraded: numeric_evidence_score=%.3f < %.2f, policy=%s, table_id=%s",
                        score,
                        threshold,
                        policy,
                        table_id or "unknown",
                    )
                    if policy == "skip_no_numeric":
                        return (None, "SKIPPED_NO_NUMERIC_EVIDENCE")
                    # downgrade_to_generic
                    if context is None:
                        context = AuditContext()
                    ctx = context.get_last_classification_context() or {}
                    ctx["downgraded_from"] = "BalanceSheetValidator"
                    ctx["numeric_evidence_score"] = score
                    context.set_last_classification_context(ctx)
                    return (GenericTableValidator(context=context), None)
            return (BalanceSheetValidator(context=context), None)
        elif result.table_type == TableType.FS_INCOME_STATEMENT:
            return (IncomeStatementValidator(context=context), None)
        elif result.table_type == TableType.FS_CASH_FLOW:
            return (CashFlowValidator(context=context), None)
        elif result.table_type == TableType.FS_EQUITY:
            return (EquityValidator(context=context), None)
        elif result.table_type == TableType.TAX_NOTE:
            return (TaxValidator(context=context), None)
        elif result.table_type == TableType.UNKNOWN:
            # Fallback to generic if not skipped, or could return None if totally unknown?
            # Legacy behavior was GenericTableValidator for unknown.
            return (GenericTableValidator(context=context), None)
        else:
            return (GenericTableValidator(context=context), None)
