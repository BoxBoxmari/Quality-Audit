"""
Rule Registry — maps table types to their audit rule classes.

Placeholder registry populated in Phase 3 when concrete rule classes
are implemented. For now, returns empty rule lists for all types.
"""

from __future__ import annotations

import logging

from .balance_sheet_rules import BalanceSheetRules
from .base_rule import AuditRule
from .breakdown_rules import BreakdownRules
from .cash_flow_rules import CashFlowRules
from .income_statement_rules import IncomeStatementRules
from .movement_rules import MovementRules

logger = logging.getLogger(__name__)


class RuleRegistry:
    """Maps table_type strings to lists of AuditRule classes.

    Usage::

        registry = RuleRegistry()
        rules = registry.resolve("INCOME_STATEMENT")
        for rule in rules:
            evidence = rule.evaluate(df, materiality=engine, ...)
    """

    def __init__(self) -> None:
        self._registry: dict[str, list[type[AuditRule]]] = {}

    def register(self, table_type: str, rule_class: type[AuditRule]) -> None:
        """Register a rule class for a table type.

        Args:
            table_type: Table classification string (e.g. "BALANCE_SHEET").
            rule_class: Concrete AuditRule subclass.
        """
        if table_type not in self._registry:
            self._registry[table_type] = []
        if rule_class not in self._registry[table_type]:
            self._registry[table_type].append(rule_class)
            logger.debug(
                "Registered rule %s for table type %s",
                rule_class.rule_id,
                table_type,
            )

    def resolve(self, table_type: str) -> list[AuditRule]:
        """Return instantiated rule objects for the given table type.

        Args:
            table_type: Table classification string.

        Returns:
            List of AuditRule instances. Empty if no rules registered.
        """
        classes = self._registry.get(table_type, [])
        return [cls() for cls in classes]

    @property
    def registered_types(self) -> list[str]:
        """Return all table types with registered rules."""
        return list(self._registry.keys())


# ---------------------------------------------------------------------------
# Default registry instance
# ---------------------------------------------------------------------------

default_registry = RuleRegistry()

# Register Phase 3 concrete rules
default_registry.register("FS_INCOME_STATEMENT", IncomeStatementRules)
default_registry.register("FS_CASH_FLOW", CashFlowRules)
default_registry.register("FS_BALANCE_SHEET", BalanceSheetRules)
default_registry.register("GENERIC_NOTE", MovementRules)
default_registry.register("FS_EQUITY", MovementRules)
default_registry.register("GENERIC_NOTE", BreakdownRules)
default_registry.register("TAX_NOTE", BreakdownRules)
