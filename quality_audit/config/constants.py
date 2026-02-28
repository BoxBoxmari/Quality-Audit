"""
Constants and configuration values for the Quality Audit application.
"""

import re
from enum import Enum

from openpyxl.styles import Alignment, Font, PatternFill

# Regex helpers
_SHEET_NAME_CLEAN_RE = re.compile(r"[:\\/*?\[\]]")
_CODE_COL_NAME = "code"
_NOTE_COL_NAME = "note"
_CODE_VALID_RE = re.compile(r"^[0-9]+[A-Z]?$")
_HEADER_DATE_RE = re.compile(r"\d{4}|\d{1,2}/\d{1,2}/\d{2,4}")

# Table types that need column-level checks
TABLES_NEED_COLUMN_CHECK = {
    "long-term prepaid expenses",
    "tangible fixed assets",
    "intangible fixed assets",
    "chi phí trả trước dài hạn",
    "tài sản cố định hữu hình",
    "tài sản cố định vô hình",
    "taxes payable to state treasury",
    "thuế và các khoản phải nộp nhà nước",
    "borrowings",
    "borrowings, bonds and finance lease liabilities",
    "short-term borrowings",
    "long-term borrowings",
}

# Form 1: Tables with possible subtotals, cross-ref at grand total
CROSS_CHECK_TABLES_FORM_1 = {
    "accounts receivable from customers",
    "accounts receivable from customers detailed by significant customer",
    "accounts receivable from customers detailed by significant customers",
    "receivables on construction contracts according to stages of completion",
    "payables on construction contracts according to stages of completion",
    "deferred tax assets and liabilities",
    "deferred tax assets",
    "deferred tax liabilities",
    "accrued expenses",
    "accrued expenses – short-term",
    "accrued expenses - short-term",
    "accrued expenses – long-term",
    "accrued expenses - long-term",
    "unearned revenue",
    "unearned revenue – short-term",
    "unearned revenue – long-term",
    "other payables",
    "other payables – short-term",
    "other payables – long-term",
    "long-term borrowings",
    "long-term borrowings, bonds and financial lease liabilities",
    "long-term bonds and financial lease liabilities",
    "long-term financial lease liabilities",
    "long-term bonds",
}

# Form 2: Tables with possible subtotals, cross-ref at both subtotal and grand total
CROSS_CHECK_TABLES_FORM_2 = {
    "revenue from sales of goods and provision of services",
    "revenue from sales of goods",
    "revenue from provision of services",
}

# Form 3: Tables without subtotals but not standard tables
CROSS_CHECK_TABLES_FORM_3 = {
    "investments",
    "trading securities",
    "held-to-maturity investments",
    "equity investments in other entities",
    "equity investments in other entity",
    "bad and doubtful debts",
    "shortage of assets awaiting resolution",
    "inventories",
    "long-term work in progress",
    "construction in progress",
    "long-term prepaid expenses",
    "accounts payable to suppliers",
    "accounts payable to suppliers detailed by significant suppliers",
    "accounts payable to suppliers detailed by significant supplier",
    "taxes and others payable to state treasury",
    "taxes and others receivable from state treasury",
    "taxes and others receivable from and payable to state treasury",
    "taxes receivable from state treasury",
    "taxes payable to state treasury",
    "short-term borrowings",
    "short-term borrowings, bonds and finance lease liabilities",
    "short-term bonds and finance lease liabilities",
    "short-term bonds",
    "preference shares",
    "provisions",
    "short-term provisions",
    "long-term provisions",
    "share capital",
    "contributed capital",
}

# Valid account codes
VALID_CODES = {"222", "223", "225", "226", "228", "229", "231", "232"}

# Tables that need separate checking logic
TABLES_NEED_CHECK_SEPARATELY = {
    "tangible fixed assets",
    "intangible fixed assets",
    "tài sản cố định hữu hình",
    "tài sản cố định vô hình",
}

# Tables without total rows
TABLES_WITHOUT_TOTAL = {
    "business costs by element",
    "Production and business costs by elements",
    "non-cash investing activity",
    "non-cash investing activities",
    "significant transactions with related parties",
    "significant transactions with related companies",
    "corresponding figures",
}

# Related party table patterns
RE_PARTY_TABLE = {
    "related parties",
    "related party",
    "related companies",
    "related company",
}

# Color definitions for Excel formatting
GREEN_FILL = PatternFill(start_color="C6EFCE", end_color="C6EFCE", fill_type="solid")
BLUE_FILL = PatternFill(start_color="90EE90", end_color="90EE90", fill_type="solid")
RED_FILL = PatternFill(start_color="FFC7CE", end_color="FFC7CE", fill_type="solid")
INFO_FILL = PatternFill(start_color="DAE8FC", end_color="DAE8FC", fill_type="solid")

GREEN_FONT = Font(color="32CD32")  # Green
RED_FONT = Font(color="FF0000")  # Red
RIGHT_ALIGN = Alignment(horizontal="right")  # Right align


# WARN Taxonomy & Traceability (Phase 1): StatusCategory for output contract
# Maps to: PASS, FAIL_DATA, FAIL_TOOL_EXTRACT, FAIL_TOOL_LOGIC, INFO_SKIPPED
# FailureReasonCode: use rule_id from RULE_TAXONOMY or context.failure_reason_code
STATUS_CATEGORY_PASS = "PASS"
STATUS_CATEGORY_FAIL_DATA = "FAIL_DATA"
STATUS_CATEGORY_FAIL_TOOL_EXTRACT = "FAIL_TOOL_EXTRACT"
STATUS_CATEGORY_FAIL_TOOL_LOGIC = "FAIL_TOOL_LOGIC"
STATUS_CATEGORY_INFO_SKIPPED = "INFO_SKIPPED"
STATUS_CATEGORY_VALUES = (
    STATUS_CATEGORY_PASS,
    STATUS_CATEGORY_FAIL_DATA,
    STATUS_CATEGORY_FAIL_TOOL_EXTRACT,
    STATUS_CATEGORY_FAIL_TOOL_LOGIC,
    STATUS_CATEGORY_INFO_SKIPPED,
)
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
