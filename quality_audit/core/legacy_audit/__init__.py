"""
Legacy baseline audit core.

Baseline source of truth:
- legacy/main.py
- legacy/Quality Audit.py

This package is the authoritative default audit rule layer.
Do not import legacy scripts at runtime.
"""

from .adapters import LegacyRuleAdapter
from .balance_sheet import get_balance_rules, get_balance_rules_new
from .cash_flow import CASH_FLOW_CODE_FORMULAS
from .catalogs import (
    CROSS_CHECK_TABLES_FORM_1,
    CROSS_CHECK_TABLES_FORM_1A,
    CROSS_CHECK_TABLES_FORM_1B,
    CROSS_CHECK_TABLES_FORM_2,
    CROSS_CHECK_TABLES_FORM_3,
    TABLES_NEED_CHECK_SEPARATELY,
    TABLES_NEED_COLUMN_CHECK,
    TABLES_WITHOUT_TOTAL,
)
from .codes import VALID_CODES
from .coloring import (
    BLUE_FILL,
    GREEN_FILL,
    GREEN_FONT,
    INFO_FILL,
    RED_FILL,
    RED_FONT,
    RIGHT_ALIGN,
)
from .headings import HEADING_ALIASES
from .provenance import BASELINE_SOURCES, RuleProvenance

__all__ = [
    "BASELINE_SOURCES",
    "RuleProvenance",
    "LegacyRuleAdapter",
    "HEADING_ALIASES",
    "TABLES_NEED_COLUMN_CHECK",
    "TABLES_NEED_CHECK_SEPARATELY",
    "TABLES_WITHOUT_TOTAL",
    "CROSS_CHECK_TABLES_FORM_1",
    "CROSS_CHECK_TABLES_FORM_1A",
    "CROSS_CHECK_TABLES_FORM_1B",
    "CROSS_CHECK_TABLES_FORM_2",
    "CROSS_CHECK_TABLES_FORM_3",
    "VALID_CODES",
    "get_balance_rules",
    "get_balance_rules_new",
    "CASH_FLOW_CODE_FORMULAS",
    "GREEN_FILL",
    "BLUE_FILL",
    "RED_FILL",
    "INFO_FILL",
    "GREEN_FONT",
    "RED_FONT",
    "RIGHT_ALIGN",
]
