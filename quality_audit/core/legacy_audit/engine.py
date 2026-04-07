"""
Legacy-authoritative audit decision engine for default runtime.

NON-RUNTIME OWNER (canonical single-path mode): retained for experimental
compatibility flows only. Production correctness is owned by legacy/main.py
via AuditService canonical runtime path.
"""

from __future__ import annotations

from typing import Any, Dict, Optional

import pandas as pd

from quality_audit.core.cache_manager import AuditContext
from quality_audit.core.validators.balance_sheet_validator import BalanceSheetValidator
from quality_audit.core.validators.base_validator import ValidationResult
from quality_audit.core.validators.cash_flow_validator import CashFlowValidator
from quality_audit.core.validators.equity_validator import EquityValidator
from quality_audit.core.validators.generic_validator import GenericTableValidator
from quality_audit.core.validators.income_statement_validator import (
    IncomeStatementValidator,
)
from quality_audit.core.validators.tax_validator import TaxValidator

from .router import route_table


class LegacyAuditEngine:
    """Runs baseline routing and dispatches to compatibility validator wrappers."""

    def __init__(self, context: Optional[AuditContext] = None):
        self.context = context or AuditContext()

    def _build_validator(self, family: str):
        if family == "balance_sheet":
            return BalanceSheetValidator(context=self.context)
        if family == "income_statement":
            return IncomeStatementValidator(context=self.context)
        if family == "cash_flow":
            return CashFlowValidator(context=self.context)
        if family == "equity":
            return EquityValidator(context=self.context)
        if family == "tax_note":
            return TaxValidator(context=self.context)
        return GenericTableValidator(context=self.context)

    @staticmethod
    def _run_validator_with_heading_attr(
        validator,
        table: pd.DataFrame,
        heading_val: str,
        table_context: Optional[Dict[str, Any]],
    ) -> ValidationResult:
        had_heading_attr = "heading" in table.attrs
        original_heading_attr = table.attrs.get("heading")
        table.attrs["heading"] = heading_val
        try:
            return validator.validate(table, heading_val, table_context=table_context)
        finally:
            if had_heading_attr:
                table.attrs["heading"] = original_heading_attr
            else:
                table.attrs.pop("heading", None)

    @staticmethod
    def _family_to_classifier_type(family: str) -> str:
        mapping = {
            "balance_sheet": "FS_BALANCE_SHEET",
            "income_statement": "FS_INCOME_STATEMENT",
            "cash_flow": "FS_CASH_FLOW",
            "equity": "FS_EQUITY",
            "tax_note": "TAX_NOTE",
            "generic_note": "GENERIC_NOTE",
        }
        return mapping.get(family, "UNKNOWN")

    def validate_table(
        self,
        table: pd.DataFrame,
        heading: Optional[str],
        table_context: Optional[Dict[str, Any]],
    ) -> ValidationResult:
        heading_val = heading or ""
        if heading_val.strip().upper().startswith("SKIPPED_"):
            return ValidationResult(
                status="INFO: Table bị skip (footer/chữ ký)",
                marks=[],
                cross_ref_marks=[],
                rule_id="SKIPPED_FOOTER_SIGNATURE",
                status_enum="INFO",
                context={
                    "heading": heading_val,
                    "reason": "Detected as footer/signature table",
                    "parity_supported": False,
                },
            )

        route = route_table(table, heading_val, table_context)
        validator = self._build_validator(route.family)
        result = self._run_validator_with_heading_attr(
            validator, table, heading_val, table_context
        )

        classifier_primary_type = self._family_to_classifier_type(route.family)
        result.context.setdefault("validator_type", type(validator).__name__)
        result.context.setdefault("parity_supported", True)
        result.context.setdefault("legacy_route_family", route.family)
        result.context.setdefault("legacy_route_reason", route.reason)
        result.context.setdefault("legacy_route_confidence", route.confidence)
        result.context.setdefault("classifier_primary_type", classifier_primary_type)
        result.context.setdefault("classifier_confidence", route.confidence)
        result.context.setdefault("captured_heading_attr", heading_val)
        return result
