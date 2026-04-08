"""
Constants and configuration values for the Quality Audit application.
"""

import re
from enum import Enum

from openpyxl.styles import Alignment, Font, PatternFill

from quality_audit.core.legacy_audit.catalogs import (
    CROSS_CHECK_TABLES_FORM_1,
    CROSS_CHECK_TABLES_FORM_2,
    CROSS_CHECK_TABLES_FORM_3,
    TABLES_NEED_CHECK_SEPARATELY,
    TABLES_NEED_COLUMN_CHECK,
    TABLES_WITHOUT_TOTAL,
)
from quality_audit.core.legacy_audit.codes import RELATED_PARTY_LABELS as RE_PARTY_TABLE
from quality_audit.core.legacy_audit.codes import (
    VALID_CODES,
)
from quality_audit.core.legacy_audit.coloring import (
    BLUE_FILL,
    GREEN_FILL,
    GREEN_FONT,
    INFO_FILL,
    RED_FILL,
    RED_FONT,
    RIGHT_ALIGN,
)

# Regex helpers
_SHEET_NAME_CLEAN_RE = re.compile(r"[:\\/*?\[\]]")
_CODE_COL_NAME = "code"
_NOTE_COL_NAME = "note"
_CODE_VALID_RE = re.compile(r"^[0-9]+[A-Z]?$")
_HEADER_DATE_RE = re.compile(r"\d{4}|\d{1,2}/\d{1,2}/\d{2,4}")

# Baseline-authoritative catalogs/codes/coloring are imported from
# quality_audit.core.legacy_audit.* and re-exported here for compatibility.


# WARN Taxonomy & Traceability (Phase 1): StatusCategory for output contract
# Maps to: PASS, FAIL_DATA, FAIL_TOOL_EXTRACT, FAIL_TOOL_LOGIC, INFO_SKIPPED, WARN
# FailureReasonCode: use rule_id from RULE_TAXONOMY or context.failure_reason_code
STATUS_CATEGORY_PASS = "PASS"
STATUS_CATEGORY_FAIL_DATA = "FAIL_DATA"
STATUS_CATEGORY_FAIL_TOOL_EXTRACT = "FAIL_TOOL_EXTRACT"
STATUS_CATEGORY_FAIL_TOOL_LOGIC = "FAIL_TOOL_LOGIC"
STATUS_CATEGORY_INFO_SKIPPED = "INFO_SKIPPED"
STATUS_CATEGORY_WARN = "WARN"
STATUS_CATEGORY_VALUES = (
    STATUS_CATEGORY_PASS,
    STATUS_CATEGORY_FAIL_DATA,
    STATUS_CATEGORY_FAIL_TOOL_EXTRACT,
    STATUS_CATEGORY_FAIL_TOOL_LOGIC,
    STATUS_CATEGORY_INFO_SKIPPED,
    STATUS_CATEGORY_WARN,
)

# WARN reason_code taxonomy (NOTE structure / ambiguity); emit in evidence.metadata["reason_code"]
WARN_REASON_UNKNOWN_TABLE_TYPE = "UNKNOWN_TABLE_TYPE"
WARN_REASON_SCOPE_UNDETERMINED = "SCOPE_UNDETERMINED"
WARN_REASON_MULTIPLE_TOTAL_CANDIDATES = "MULTIPLE_TOTAL_CANDIDATES"
WARN_REASON_STRUCTURE_INCOMPLETE = "STRUCTURE_INCOMPLETE"
WARN_REASON_NUMERIC_COLUMNS_AMBIGUOUS = "NUMERIC_COLUMNS_AMBIGUOUS"
WARN_REASON_HEADER_CONFUSION = "HEADER_CONFUSION"
WARN_REASON_STRUCTURE_UNDETERMINED = "STRUCTURE_UNDETERMINED"
WARN_REASON_ROUTE_CORRECTION = "ROUTE_CORRECTION"
WARN_REASON_CODES = frozenset(
    {
        WARN_REASON_UNKNOWN_TABLE_TYPE,
        WARN_REASON_SCOPE_UNDETERMINED,
        WARN_REASON_MULTIPLE_TOTAL_CANDIDATES,
        WARN_REASON_STRUCTURE_INCOMPLETE,
        WARN_REASON_NUMERIC_COLUMNS_AMBIGUOUS,
        WARN_REASON_HEADER_CONFUSION,
        WARN_REASON_STRUCTURE_UNDETERMINED,
    }
)

# Skip-reason taxonomy for numeric tables with zero evidence (P0 observability)
SKIP_REASON_INVALID_TABLE_INFO = "INVALID_TABLE_INFO"
SKIP_REASON_STRUCTURE_UNDETERMINED = "STRUCTURE_UNDETERMINED"
SKIP_REASON_NO_RULES_FOR_TYPE = "NO_RULES_FOR_TYPE"
SKIP_REASON_RULES_RAN_NO_EVIDENCE = "RULES_RAN_BUT_NO_EVIDENCE"
SKIP_REASON_PARSE_FAIL_NUMERIC = "PARSE_FAIL_NUMERIC"
SKIP_REASON_REGISTRY_MISS = "REGISTRY_MISS"
SKIP_REASON_ERROR_IN_RULE = "ERROR_IN_RULE"

# Rule IDs that imply FAIL_TOOL_EXTRACT (extraction/structure fault)
FAIL_TOOL_EXTRACT_NO_TOTALS = "FAIL_TOOL_EXTRACT_NO_TOTALS"
FAIL_TOOL_EXTRACT_NO_NUMERIC = "FAIL_TOOL_EXTRACT_NO_NUMERIC"
FAIL_TOOL_EXTRACT_MISSING_PERIOD_COLUMN = "FAIL_TOOL_EXTRACT_MISSING_PERIOD_COLUMN"
FAIL_TOOL_EXTRACT_RULE_IDS = frozenset(
    {
        "FAIL_TOOL_EXTRACT_GRID_CORRUPTION",
        "FAIL_TOOL_EXTRACT_HEADER_COLLAPSE",
        "FAIL_TOOL_EXTRACT_DUPLICATE_PERIODS",
        "FAIL_TOOL_EXTRACT_LOW_QUALITY",
        FAIL_TOOL_EXTRACT_NO_TOTALS,
        FAIL_TOOL_EXTRACT_NO_NUMERIC,
        FAIL_TOOL_EXTRACT_MISSING_PERIOD_COLUMN,
    }
)
FAIL_TOOL_LOGIC_RULE_IDS = frozenset({"FAIL_TOOL_LOGIC_VALIDATOR_CRASH"})

# Evidence gating (Spine fix 2): standardized failure_reason_code for gate decisions
GATE_REASON_NO_NUMERIC_COLUMNS = "NO_NUMERIC_COLUMNS"
GATE_REASON_LOW_NUMERIC_DENSITY = "LOW_NUMERIC_DENSITY"
GATE_REASON_NO_DETAIL_ROWS = "NO_DETAIL_ROWS"
GATE_REASON_NO_TOTAL_ROW_MATCH = "NO_TOTAL_ROW_MATCH"
GATE_REASON_LOW_EXTRACTION_QUALITY = "LOW_EXTRACTION_QUALITY"


# SCRUM-7: Rule Criticality Enum
class RuleCriticality(Enum):
    """Criticality levels for validation rules."""

    HIGH = "HIGH"
    MEDIUM = "MEDIUM"
    LOW = "LOW"

    @property
    def name(self) -> str:
        """Return the enum value as string."""
        return self.value


# SCRUM-7: Scoring Configuration
class ScoringConfig:
    """Configuration for scoring and severity calculation."""

    # Difference thresholds for severity calculation (in absolute value)
    DIFF_THRESHOLD_CRITICAL = 1000000.0  # >= 1M: Critical
    DIFF_THRESHOLD_HIGH = 100000.0  # >= 100K: High
    DIFF_THRESHOLD_MEDIUM = 10000.0  # >= 10K: Medium
    # < 10K: Low


# SCRUM-7: Rule Taxonomy
# Maps rule_id -> (family, criticality, root_cause)
# family: Rule family (e.g., "FS Casting", "Cross-Check", "Structure")
# criticality: RuleCriticality enum value
# root_cause: Root cause tag (e.g., "calculation", "mapping", "subtotal")
RULE_TAXONOMY = {
    # Math/Calculation rules
    "MATH_EQ": ("FS Casting", RuleCriticality.HIGH, "calculation"),
    "TAX_RATE_CALCULATION_STEP2": ("FS Casting", RuleCriticality.HIGH, "calculation"),
    "TAX_RATE_CALCULATION_STEP3": ("FS Casting", RuleCriticality.HIGH, "calculation"),
    "TAX_REMAINING_TABLE_GRAND_TOTAL": (
        "FS Casting",
        RuleCriticality.MEDIUM,
        "calculation",
    ),
    # Cross-reference rules
    "CROSS_CHECK_MISMATCH": ("Cross-Check", RuleCriticality.HIGH, "cross_ref"),
    # Validation rules by statement type
    "BALANCE_SHEET_VALIDATION": ("Structure", RuleCriticality.MEDIUM, "structure"),
    "INCOME_STATEMENT_VALIDATION": ("Structure", RuleCriticality.MEDIUM, "structure"),
    "CASH_FLOW_VALIDATION": ("Structure", RuleCriticality.MEDIUM, "structure"),
    "EQUITY_VALIDATION": ("Structure", RuleCriticality.MEDIUM, "structure"),
    "TAX_VALIDATION": ("FS Casting", RuleCriticality.HIGH, "calculation"),
    "FIXED_ASSET_VALIDATION": ("Structure", RuleCriticality.MEDIUM, "structure"),
    "COLUMN_TOTAL_VALIDATION": ("FS Casting", RuleCriticality.MEDIUM, "calculation"),
    "ROW_TOTAL_GRAND_TOTAL": ("FS Casting", RuleCriticality.MEDIUM, "subtotal"),
    # Error/Exception rules
    "VALIDATION_INDEX_ERROR": ("Error", RuleCriticality.HIGH, "general"),
    "VALIDATION_KEY_ERROR": ("Error", RuleCriticality.HIGH, "general"),
    "VALIDATION_UNICODE_ERROR": ("Error", RuleCriticality.MEDIUM, "general"),
    "VALIDATION_VALUE_ERROR": ("Error", RuleCriticality.MEDIUM, "general"),
    "VALIDATION_UNEXPECTED_ERROR": ("Error", RuleCriticality.HIGH, "general"),
    "VALIDATOR_FACTORY_ERROR": ("Error", RuleCriticality.HIGH, "general"),
    # Info/Skip rules
    "SKIPPED_FOOTER_SIGNATURE": ("Info", RuleCriticality.LOW, "general"),
    "TABLE_EMPTY": ("Info", RuleCriticality.LOW, "structure"),
    "TAX_NO_PROFIT_ROW": ("Info", RuleCriticality.LOW, "structure"),
    "TABLE_NO_TOTAL_ROW": ("Info", RuleCriticality.LOW, "structure"),
    "NOTE_STRUCTURE_UNDETERMINED": ("Info", RuleCriticality.LOW, "structure"),
    "UNVERIFIED_NUMERIC_TABLE": ("Info", RuleCriticality.LOW, "structure"),
    # FAIL_TOOL_* taxonomy (tool faults, not audit findings)
    "FAIL_TOOL_EXTRACT_GRID_CORRUPTION": (
        "Tool",
        RuleCriticality.HIGH,
        "extraction",
    ),
    "FAIL_TOOL_EXTRACT_HEADER_COLLAPSE": (
        "Tool",
        RuleCriticality.HIGH,
        "extraction",
    ),
    "FAIL_TOOL_EXTRACT_DUPLICATE_PERIODS": (
        "Tool",
        RuleCriticality.HIGH,
        "extraction",
    ),
    "FAIL_TOOL_EXTRACT_LOW_QUALITY": ("Tool", RuleCriticality.HIGH, "extraction"),
    "FAIL_TOOL_LOGIC_VALIDATOR_CRASH": (
        "Tool",
        RuleCriticality.HIGH,
        "logic",
    ),
    "FAIL_TOOL_EXTRACT_NO_TOTALS": ("Tool", RuleCriticality.HIGH, "extraction"),
    "FAIL_TOOL_EXTRACT_NO_NUMERIC": ("Tool", RuleCriticality.HIGH, "extraction"),
    "FAIL_TOOL_EXTRACT_MISSING_PERIOD_COLUMN": (
        "Tool",
        RuleCriticality.HIGH,
        "extraction",
    ),
    "TABLE_NO_NUMERIC_STRUCTURE": ("Info", RuleCriticality.LOW, "structure"),
    "EXTRACTION_FALLBACK_OOXML": ("Tool", RuleCriticality.MEDIUM, "extraction"),
    "NO_TOTAL_AND_NO_COLUMN_CHECK": ("Info", RuleCriticality.LOW, "structure"),
}

# Phase 4: Totals detection tolerance (Rule C) and min columns threshold
# Used in base_validator._find_total_row for sum-of-previous equality
# Equity formula: slightly looser relative tolerance for rounding across balance rows
EQUITY_TOLERANCE_REL = 0.012
# Rule C: require at least this fraction of amount columns to satisfy sum-of-previous
TOTALS_RULE_C_MIN_COLUMNS_PCT = 0.5
# R3: Reject total candidate in top half when more than this many numeric rows below
TOTALS_GUARDRAIL_NUMERIC_BELOW = 3
# R3: Legacy "empty row before" considers only last N or bottom-half numeric rows
TOTALS_LEGACY_BOTTOM_N = 5
