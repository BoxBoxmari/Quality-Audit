"""
Base validator class for financial statement validation.
"""

import logging
from abc import ABC, abstractmethod
from typing import Any, Dict, List, Optional, Sequence, Tuple

import pandas as pd

from ...config.constants import (
    FAIL_TOOL_EXTRACT_RULE_IDS,
    FAIL_TOOL_LOGIC_RULE_IDS,
    GATE_REASON_LOW_EXTRACTION_QUALITY,
    RULE_TAXONOMY,
    STATUS_CATEGORY_FAIL_DATA,
    STATUS_CATEGORY_FAIL_TOOL_EXTRACT,
    STATUS_CATEGORY_FAIL_TOOL_LOGIC,
    STATUS_CATEGORY_INFO_SKIPPED,
    STATUS_CATEGORY_PASS,
    TABLES_NEED_CHECK_SEPARATELY,
    TOTALS_GUARDRAIL_NUMERIC_BELOW,
    TOTALS_LEGACY_BOTTOM_N,
    VALID_CODES,
    RuleCriticality,
    ScoringConfig,
)
from ...config.feature_flags import get_feature_flags
from ...utils.column_detector import ColumnDetector, ColumnType
from ...utils.column_roles import (
    ROLE_CODE,
    get_columns_to_exclude_from_sum,
    infer_column_roles,
    infer_column_roles_and_exclude,
)
from ...utils.numeric_utils import (
    compute_numeric_evidence_score,
    is_year_like_value,
    normalize_numeric_column,
)
from ...utils.table_canonicalizer import TableMeta, canonicalize_table
from ...utils.table_normalizer import TableNormalizer
from ..cache_manager import AuditContext, cross_check_cache, cross_check_marks

logger = logging.getLogger(__name__)


class ValidationResult:
    """Standardized validation result structure."""

    def __init__(
        self,
        status: str,
        marks: Optional[List[Dict]] = None,
        cross_ref_marks: Optional[List[Dict]] = None,
        rule_id: Optional[str] = None,
        status_enum: Optional[str] = None,
        context: Optional[Dict] = None,
        exception_type: Optional[str] = None,
        exception_message: Optional[str] = None,
        # SCRUM-6: Structured diagnostics
        detected_columns: Optional[List[str]] = None,
        block_indices: Optional[List[Tuple[int, int]]] = None,
        # SCRUM-7: Reporting & UX
        severity: Optional[str] = None,
        confidence: Optional[str] = None,
        evidence: Optional[List[Dict[str, Any]]] = None,
        table_id: Optional[str] = None,
        # SCRUM-7 P1: Root Cause grouping
        root_cause: Optional[str] = None,
        # Phase 0: Observability - number of checks actually executed
        assertions_count: int = 0,
    ):
        """
        Initialize validation result.

        Args:
            status: Human-readable status message
            marks: List of cell marks for formatting
            cross_ref_marks: List of cross-reference marks
            rule_id: Stable identifier for the validation rule (machine-readable)
            status_enum: Status as enum (PASS/FAIL/WARN/ERROR)
            context: Additional context dictionary (table info, detected columns, etc.)
            exception_type: Exception type if validation failed with exception
            exception_message: Exception message if validation failed with exception
            detected_columns: SCRUM-6 - List of detected column names in table
            block_indices: SCRUM-6 - List of (start, end) block indices for segmentation
            severity: SCRUM-7 - Severity level (HIGH/MED/LOW)
            confidence: SCRUM-7 - Confidence level (HIGH/MED/LOW)
            evidence: SCRUM-7 - List of evidence items (top diffs)
            table_id: SCRUM-7 - Stable table identifier
        """
        self.status = status
        self.marks = marks or []
        self.cross_ref_marks = cross_ref_marks or []
        self.rule_id = rule_id or self._infer_rule_id_from_status(status)
        self.status_enum = status_enum or self._infer_status_enum(status)
        self.context = context or {}
        self.exception_type = exception_type
        self.exception_message = exception_message
        # SCRUM-6: Structured diagnostics
        self.detected_columns = detected_columns
        self.block_indices = block_indices
        # SCRUM-7: Reporting & UX
        self.severity = severity
        self.confidence = confidence
        self.evidence = evidence or []
        self.table_id = table_id
        # SCRUM-7 P1: Root Cause grouping
        self.root_cause = root_cause
        # Phase 0: Observability
        self.assertions_count = assertions_count

        # SCRUM-8: Defensive filtering for visual conflicts (Red Fill + Green Text)
        if self.status_enum in ("FAIL", "FAIL_TOOL_EXTRACT", "FAIL_TOOL_LOGIC"):
            # If table failed, strip out PASS marks to avoid visual noise/confusion
            # This ensures Red Fills (failures) are the primary focus
            # Keep NO_EVIDENCE marks (ok=True) for reporting when equity_no_evidence_not_fail etc.
            if self.marks:
                self.marks = [
                    m
                    for m in self.marks
                    if not m.get("ok", True)
                    or ("NO_EVIDENCE" in (m.get("comment") or ""))
                ]

            # Filter cross-ref marks (Fix for TaxValidator conflicts)
            if self.cross_ref_marks:
                self.cross_ref_marks = [
                    m for m in self.cross_ref_marks if not m.get("ok", True)
                ]

        # Check for conflicts between marks and cross-refs (log warning or resolve)
        # Note: We don't modify cross_ref_marks here as they serve different purpose (BSPL checks),
        # but formatter safeguards will prevent visual collision.

        # P0-R3: Normalize marks schema
        self.marks = [self._normalize_mark(m) for m in self.marks]

    def _normalize_mark(self, mark: Dict) -> Dict:
        """
        P0-R3: Normalize mark dictionary to ensure required fields.
        """
        if "diff" not in mark:
            mark["diff"] = 0.0
        if "rule_id" not in mark:
            mark["rule_id"] = self.rule_id or "UNKNOWN"
        return mark

    def _infer_status_enum(self, status: str) -> str:
        """
        Infer status enum from status message.

        Taxonomy: PASS, FAIL, FAIL_DATA, FAIL_TOOL_EXTRACT, FAIL_TOOL_LOGIC,
        WARN, INFO, INFO_SKIPPED, ERROR, UNKNOWN.
        Backward compatible: existing PASS/FAIL/WARN/INFO/ERROR preserved.

        Args:
            status: Status message string

        Returns:
            str: Status enum
        """
        status_lower = status.lower()
        if (
            "pass" in status_lower
            or "khớp" in status_lower
            or "success" in status_lower
        ):
            return "PASS"
        if (
            "fail_tool_extract" in status_lower
            or "grid corruption" in status_lower
            or "header collapse" in status_lower
            or "duplicate period" in status_lower
            or "extraction" in status_lower
            and ("failed" in status_lower or "low quality" in status_lower)
        ):
            return "FAIL_TOOL_EXTRACT"
        if (
            "fail_tool_logic" in status_lower
            or "validator crash" in status_lower
            or "validator exception" in status_lower
        ):
            return "FAIL_TOOL_LOGIC"
        if (
            "info_skipped" in status_lower
            or "non-financial" in status_lower
            or "footer" in status_lower
            or "signature" in status_lower
            or "narrative" in status_lower
            or "skipped" in status_lower
        ):
            return "INFO_SKIPPED"
        if "fail" in status_lower or "sai lệch" in status_lower:
            return "FAIL"
        if (
            "warn" in status_lower
            or "không tìm thấy" in status_lower
            or "info" in status_lower
        ):
            return "WARN"
        if "error" in status_lower:
            return "ERROR"
        return "UNKNOWN"

    def _infer_rule_id_from_status(self, status: str) -> str:
        """
        Infer rule_id from status message as fallback.

        Args:
            status: Status message string

        Returns:
            str: Rule ID or "UNKNOWN"
        """
        # SCRUM-8: First try to extract from marks (prioritize FAIL marks)
        if hasattr(self, "marks") and self.marks:
            # Prioritize rule_ids from FAIL marks
            fail_rule_ids = [
                m.get("rule_id")
                for m in self.marks
                if not m.get("ok") and m.get("rule_id")
            ]
            if fail_rule_ids and fail_rule_ids[0]:
                return str(fail_rule_ids[0])
            # Fallback: any mark with rule_id
            all_rule_ids = [m.get("rule_id") for m in self.marks if m.get("rule_id")]
            if all_rule_ids and all_rule_ids[0]:
                return str(all_rule_ids[0])

        # Legacy fallback: infer from status text
        status_lower = status.lower()
        if "balance sheet" in status_lower:
            return "BALANCE_SHEET_VALIDATION"
        elif "statement of income" in status_lower or "income" in status_lower:
            return "INCOME_STATEMENT_VALIDATION"
        elif "cash flows" in status_lower or "cash flow" in status_lower:
            return "CASH_FLOW_VALIDATION"
        elif "equity" in status_lower:
            return "EQUITY_VALIDATION"
        elif "tax" in status_lower or "reconciliation" in status_lower:
            return "TAX_VALIDATION"
        elif "fixed asset" in status_lower:
            return "FIXED_ASSET_VALIDATION"
        elif "cột" in status_lower or "column" in status_lower:
            return "COLUMN_TOTAL_VALIDATION"
        elif "kiểm tra công thức" in status_lower or "sai lệch" in status_lower:
            return "ROW_TOTAL_GRAND_TOTAL"
        return "UNKNOWN"

    def _get_status_category_and_reason(self) -> Tuple[str, str]:
        """
        WARN Taxonomy Phase 1: Map (status_enum, rule_id) to status_category
        and failure_reason_code for output contract.
        """
        status_enum = self.status_enum or "UNKNOWN"
        rule_id = self.rule_id or ""
        failure_reason_code = (
            rule_id or (self.context or {}).get("failure_reason_code") or "UNKNOWN"
        )
        if status_enum == "PASS":
            return STATUS_CATEGORY_PASS, failure_reason_code
        if status_enum == "INFO_SKIPPED":
            return STATUS_CATEGORY_INFO_SKIPPED, failure_reason_code
        if rule_id in FAIL_TOOL_EXTRACT_RULE_IDS or status_enum == "FAIL_TOOL_EXTRACT":
            return STATUS_CATEGORY_FAIL_TOOL_EXTRACT, failure_reason_code
        if rule_id in FAIL_TOOL_LOGIC_RULE_IDS or status_enum == "FAIL_TOOL_LOGIC":
            return STATUS_CATEGORY_FAIL_TOOL_LOGIC, failure_reason_code
        if status_enum in ("FAIL", "WARN", "ERROR"):
            return STATUS_CATEGORY_FAIL_DATA, failure_reason_code
        if status_enum == "INFO":
            return STATUS_CATEGORY_INFO_SKIPPED, failure_reason_code
        return STATUS_CATEGORY_FAIL_DATA, failure_reason_code

    def to_dict(self) -> Dict[str, Any]:
        """Convert to dictionary format.

        SCRUM-6: Includes structured diagnostics fields.
        """
        status_category, failure_reason_code = self._get_status_category_and_reason()
        result: Dict[str, Any] = {
            "status": self.status,
            "marks": self.marks,
            "cross_ref_marks": self.cross_ref_marks,
            "rule_id": self.rule_id,
            "status_enum": self.status_enum,
            "context": self.context,
            "status_category": status_category,
            "failure_reason_code": failure_reason_code,
        }
        if self.exception_type:
            result["exception_type"] = self.exception_type
        if self.exception_message:
            result["exception_message"] = self.exception_message
        # SCRUM-6: Structured diagnostics
        if self.detected_columns:
            result["detected_columns"] = self.detected_columns
        if self.block_indices:
            result["block_indices"] = self.block_indices
        # SCRUM-7: Reporting & UX
        if self.severity:
            result["severity"] = self.severity
        if self.confidence:
            result["confidence"] = self.confidence
        if self.evidence:
            result["evidence"] = self.evidence
        if self.table_id:
            result["table_id"] = self.table_id
        # SCRUM-7 P1: Root Cause grouping
        if self.root_cause:
            result["root_cause"] = self.root_cause
        # Phase 0: Observability
        result["assertions_count"] = int(getattr(self, "assertions_count", 0))
        return result


class BaseValidator(ABC):
    """
    Abstract base class for financial statement validators.

    Defines the interface that all validators must implement.
    """

    def __init__(self, cache_manager=None, context: Optional["AuditContext"] = None):
        """
        Initialize validator.

        Args:
            cache_manager: DEPRECATED - Cache manager for cross-referencing data
            context: Audit context containing cache and shared state
        """
        self.context = context
        self.cache_manager = cache_manager or (context.cache if context else None)

    def _check_extraction_quality(
        self, table_context: Optional[Dict]
    ) -> Optional[ValidationResult]:
        """
        Phase 7: If extraction quality is low or flags indicate extraction failure,
        return a FAIL_TOOL_EXTRACT result for early exit. Otherwise return None.

        Phase 9 (Render-First): Also marks BORDERLINE_CONFIDENCE for WARN capping.
        """
        if not table_context:
            return None
        quality_score = table_context.get("quality_score")
        quality_flags = table_context.get("quality_flags") or []
        bad_flags = {"GRID_CORRUPTION", "DUPLICATE_PERIODS"}
        # Only fail on low score when hard extraction flags are present (Group 2 fix).
        # Low score alone (e.g. from vmerge_misalign) does not block validation.
        if (
            quality_score is not None
            and quality_score < 0.6
            and any(f in bad_flags for f in quality_flags)
        ):
            ctx = dict(table_context)
            ctx["gate_decision"] = "EXTRACT_ERROR"
            ctx["failure_reason_code"] = GATE_REASON_LOW_EXTRACTION_QUALITY
            ctx["evidence"] = {
                "quality_score": quality_score,
                "quality_flags": quality_flags,
            }
            return ValidationResult(
                status="FAIL_TOOL_EXTRACT: Low extraction quality",
                marks=[],
                cross_ref_marks=[],
                rule_id="FAIL_TOOL_EXTRACT_LOW_QUALITY",
                status_enum="FAIL_TOOL_EXTRACT",
                context=ctx,
            )
        if any(f in bad_flags for f in quality_flags):
            ctx = dict(table_context)
            ctx["gate_decision"] = "EXTRACT_ERROR"
            ctx["failure_reason_code"] = GATE_REASON_LOW_EXTRACTION_QUALITY
            ctx["evidence"] = {
                "quality_score": quality_score,
                "quality_flags": quality_flags,
            }
            return ValidationResult(
                status="FAIL_TOOL_EXTRACT: Grid or period extraction issue",
                marks=[],
                cross_ref_marks=[],
                rule_id="FAIL_TOOL_EXTRACT_GRID_CORRUPTION",
                status_enum="FAIL_TOOL_EXTRACT",
                context=ctx,
            )
        return None

    def _should_cap_to_warn(self, table_context: Optional[Dict]) -> bool:
        """
        Phase 9 (Render-First): Check if PASS should be capped to WARN due to
        borderline extraction confidence.

        When using render-first extractor with BORDERLINE_CONFIDENCE, we don't
        have sufficient confidence to assert PASS. Instead, cap to WARN.

        Ticket 6: Also cap when extraction_engine is ooxml_fallback.

        Args:
            table_context: Extraction metadata from WordReader.

        Returns:
            bool: True if PASS should be capped to WARN.
        """
        if not table_context:
            return False
        quality_flags = table_context.get("quality_flags") or []
        # Check for borderline confidence from render-first extractor
        if "BORDERLINE_CONFIDENCE" in quality_flags:
            return True
        # Ticket 6: Cap PASS when using OOXML fallback extraction
        if table_context.get("extraction_engine") == "ooxml_fallback":
            return True
        quality_score = table_context.get("quality_score")
        return quality_score is not None and 0.6 <= quality_score < 0.85

    def _apply_warn_capping(
        self, result: "ValidationResult", table_context: Optional[Dict]
    ) -> "ValidationResult":
        """
        Phase 9 (Render-First): Apply WARN capping to a validation result
        if extraction confidence is borderline.

        Args:
            result: Original validation result.
            table_context: Extraction metadata.

        Returns:
            ValidationResult: Possibly modified result with WARN capping.
        """
        if not self._should_cap_to_warn(table_context):
            return result

        # Only cap PASS to WARN, leave FAIL and WARN as-is
        if result.status_enum != "PASS":
            return result

        # Cap to WARN
        import logging

        logger = logging.getLogger(__name__)
        logger.info(
            "Capping PASS to WARN due to borderline extraction confidence "
            "(quality_score=%.2f, flags=%s)",
            (table_context or {}).get("quality_score", 0),
            (table_context or {}).get("quality_flags", []),
        )

        # Modify result (shallow copy to avoid side effects)
        result.status_enum = "WARN"
        result.status = f"WARN (capped): {result.status}"
        if "BORDERLINE_EXTRACTION_CONFIDENCE" not in (result.context or {}):
            if result.context is None:
                result.context = {}
            result.context["BORDERLINE_EXTRACTION_CONFIDENCE"] = True
            result.context["original_status_enum"] = "PASS"

        return result

    def _enforce_pass_gating(
        self,
        result: "ValidationResult",
        assertions_count: int,
        numeric_evidence_score: float,
        threshold: float = 0.25,
    ) -> "ValidationResult":
        """
        Enforce PASS gating: only allow PASS when there is at least one assertion
        and sufficient numeric evidence. Override to INFO_SKIPPED or FAIL_TOOL_EXTRACT
        when gating fails; set reason_code in result.context.
        """
        if result.status_enum != "PASS":
            return result
        if result.context is None:
            result.context = {}
        if assertions_count == 0:
            flags = get_feature_flags()
            if flags.get("treat_no_assertion_as_pass", False):
                result.context["no_assertion_reason"] = result.context.get(
                    "no_assertion_reason", "NOT_APPLICABLE"
                )
                logger.info(
                    "PASS gating: kept PASS (treat_no_assertion_as_pass=True, assertions_count=0)"
                )
                return result
            result.status_enum = "INFO_SKIPPED"
            result.status = "INFO_SKIPPED: No assertions executed"
            result.context["failure_reason_code"] = "NO_ASSERTIONS"
            logger.info("PASS gating: overrode to INFO_SKIPPED (assertions_count=0)")
            return result
        if numeric_evidence_score < threshold:
            result.status_enum = "FAIL_TOOL_EXTRACT"
            result.status = (
                f"FAIL_TOOL_EXTRACT: Insufficient numeric evidence "
                f"(score={numeric_evidence_score:.3f} < {threshold:.2f})"
            )
            result.context["failure_reason_code"] = "NO_NUMERIC_EVIDENCE"
            logger.info(
                "PASS gating: overrode to FAIL_TOOL_EXTRACT "
                "(numeric_evidence_score=%.3f < %.2f)",
                numeric_evidence_score,
                threshold,
            )
            return result
        return result

    @abstractmethod
    def validate(
        self,
        df: pd.DataFrame,
        heading: Optional[str] = None,
        table_context: Optional[Dict] = None,
    ) -> ValidationResult:
        """
        Validate a financial statement table.

        Args:
            df: DataFrame containing the table data
            heading: Table heading for context
            table_context: Optional extraction metadata (quality_score, quality_flags)

        Returns:
            ValidationResult: Validation results with status and marks
        """
        pass

    def _get_roles_context(self) -> Dict[str, str]:
        """Build context dict for column_roles (table_id, heading) from current table context."""
        ctx = getattr(self, "_current_table_context", None) or {}
        return {
            "table_id": ctx.get("table_id", ""),
            "heading": ctx.get("heading", ""),
        }

    def create_mark(
        self,
        row: int,
        col: int,
        ok: bool,
        value: Any,
        diff: float = 0.0,
        rule_id: str = "UNKNOWN",
        comment: str = "",
    ) -> Dict[str, Any]:
        """
        P0-R3: Create a standardized validation mark.

        Args:
            row: Row index (0-based)
            col: Col index (0-based)
            ok: Validation status (True=PASS, False=FAIL)
            value: Cell value
            diff: Difference magnitude (default 0.0)
            rule_id: Rule ID identifier
            comment: Human readable comment

        Returns:
            Dict: Standardized mark dictionary
        """
        return {
            "row": row,
            "col": col,
            "ok": ok,
            "value": value,
            "diff": float(diff) if diff is not None else 0.0,
            "rule_id": rule_id,
            "comment": comment,
        }

    def _validate_dataframe_bounds(
        self, df: pd.DataFrame, row_idx: int, col_idx: int, context: str = ""
    ) -> bool:
        """
        P0-R2: Validate DataFrame bounds before accessing indices.

        Args:
            df: DataFrame to validate
            row_idx: Row index to check
            col_idx: Column index to check
            context: Context string for error messages

        Returns:
            bool: True if indices are valid, False otherwise
        """
        if df.empty:
            return False

        if row_idx < 0 or row_idx >= len(df):
            return False

        return not (col_idx < 0 or col_idx >= len(df.columns))

    def _safe_get_cell(
        self, df: pd.DataFrame, row_idx: int, col_idx: int, default: Any = None
    ) -> Any:
        """
        P0-R2: Safely get cell value with bounds checking.

        Args:
            df: DataFrame to access
            row_idx: Row index
            col_idx: Column index
            default: Default value if out of bounds

        Returns:
            Any: Cell value or default
        """
        if not self._validate_dataframe_bounds(df, row_idx, col_idx):
            return default

        try:
            return df.iloc[row_idx, col_idx]
        except (IndexError, KeyError):
            return default

    def _find_header_row(
        self, df: pd.DataFrame, code_col_name: str = "code"
    ) -> Optional[int]:
        """
        Find the header row containing the code column.

        P1-R1: Enhanced to support multi-row headers by scanning multiple rows.

        Args:
            df: DataFrame to search
            code_col_name: Name of the code column

        Returns:
            Optional[int]: Index of header row, or None if not found
        """
        if df.empty:
            return None

        # P1-R1: Scan multiple rows for header (support multi-row headers)
        max_header_rows = min(5, len(df))  # Check up to 5 rows for header

        for i in range(max_header_rows):
            if not self._validate_dataframe_bounds(df, i, 0):
                continue

            try:
                row_strs = df.iloc[i].astype(str).str.lower()
                if row_strs.str.contains(code_col_name.lower()).any():
                    return i
            except (IndexError, KeyError):
                continue

        return None

    def _find_multi_row_header(
        self, df: pd.DataFrame, code_col_name: str = "code"
    ) -> Optional[Tuple[int, List[str]]]:
        """
        P1-R1: Find multi-row header and merge header information.

        Args:
            df: DataFrame to search
            code_col_name: Name of the code column

        Returns:
            Optional[Tuple[int, List[str]]]: (header_start_idx, merged_header_columns) or None
        """
        if df.empty:
            return None

        max_header_rows = min(5, len(df))

        # Find first row with code column
        header_start = None
        for i in range(max_header_rows):
            if not self._validate_dataframe_bounds(df, i, 0):
                continue

            try:
                row_strs = df.iloc[i].astype(str).str.lower()
                if row_strs.str.contains(code_col_name.lower()).any():
                    header_start = i
                    break
            except (IndexError, KeyError):
                continue

        if header_start is None:
            return None

        # Merge header rows (combine non-empty cells from multiple rows)
        merged_header = []
        max_cols = len(df.columns) if not df.empty else 0

        for col_idx in range(max_cols):
            header_parts = []
            for row_offset in range(min(3, len(df) - header_start)):
                row_idx = header_start + row_offset
                if self._validate_dataframe_bounds(df, row_idx, col_idx):
                    cell_val = str(df.iloc[row_idx, col_idx]).strip()
                    if cell_val and cell_val.lower() not in ["", "nan", "none"]:
                        header_parts.append(cell_val)

            # Combine header parts (e.g., "2024" + "VND" → "2024 VND")
            merged_cell = (
                " ".join(header_parts) if header_parts else f"Column{col_idx + 1}"
            )
            merged_header.append(merged_cell)

        return (header_start, merged_header)

    def _normalize_table_with_metadata(
        self,
        df: pd.DataFrame,
        heading: Optional[str] = None,
        table_context: Optional[Dict[str, Any]] = None,
    ) -> Tuple[pd.DataFrame, Dict[str, Any]]:
        """
        Normalize table using TableNormalizer and return normalized DataFrame with metadata.

        This method provides a centralized way to normalize table headers, detect canonical
        columns (Code, current year, prior year), and return metadata for validators to use.
        When enable_canonicalize_validator is True, runs canonicalize_table first and uses
        the canonicalized DataFrame for normalization; logs AUTO_CANONICALIZED when applicable.

        Args:
            df: Raw DataFrame to normalize
            heading: Optional table heading for context
            table_context: Optional dict with table_id, table_no, docx_grid_cols, source

        Returns:
            Tuple[pd.DataFrame, Dict[str, Any]]: (normalized_df, metadata)
            metadata contains:
                - code_column: Detected Code column name (or None)
                - current_year_column: Detected current year column name (or None)
                - prior_year_column: Detected prior year column name (or None)
                - header_row_idx: Index of header row if found (or None)
                - normalization_applied: Whether normalization was applied
                - canonicalization_applied: Whether canonicalize_table was applied (when flag on)
                - canon_report: Canon report dict when canonicalization was applied
        """
        if df.empty:
            empty_metadata: Dict[str, Any] = {
                "code_column": None,
                "code_columns": [],
                "current_year_column": None,
                "prior_year_column": None,
                "header_row_idx": None,
                "normalization_applied": False,
                "normalization_error": None,
                "note_column": None,
            }
            # Record for observability (per-table logging) without changing behavior.
            context: Optional[AuditContext] = getattr(self, "context", None)
            if context is not None and hasattr(
                context, "set_last_normalization_metadata"
            ):
                context.set_last_normalization_metadata(empty_metadata)
            return df, empty_metadata

        # Canonicalize when flag is on (shared API used by writer and validators)
        canon_meta: Dict[str, Any] = {
            "canonicalization_applied": False,
            "canon_report": None,
        }
        if get_feature_flags().get("enable_canonicalize_validator", True):
            table_meta = TableMeta(
                table_id=table_context.get("table_id") if table_context else None,
                table_no=table_context.get("table_no") if table_context else None,
                docx_grid_cols=(
                    table_context.get("docx_grid_cols") if table_context else None
                ),
                title=heading,
                source=table_context.get("source") if table_context else None,
            )
            df_canon, canon_report = canonicalize_table(df, table_meta)
            any_canon_flag = (
                canon_report.has_index_row
                or canon_report.has_duplicate_headers
                or canon_report.has_code_duplicates
                or canon_report.header_explode
            )
            if any_canon_flag:
                logger.info(
                    "AUTO_CANONICALIZED table (before_shape=%s, after_shape=%s, flags=%s)",
                    canon_report.before_shape,
                    canon_report.after_shape,
                    (
                        canon_report.has_index_row,
                        canon_report.has_duplicate_headers,
                        canon_report.has_code_duplicates,
                        canon_report.header_explode,
                    ),
                )
                df = df_canon
            canon_meta = {
                "canonicalization_applied": any_canon_flag,
                "canon_report": {
                    "before_shape": canon_report.before_shape,
                    "after_shape": canon_report.after_shape,
                    "has_index_row": canon_report.has_index_row,
                    "has_duplicate_headers": canon_report.has_duplicate_headers,
                    "has_code_duplicates": canon_report.has_code_duplicates,
                    "header_explode": canon_report.header_explode,
                    "actions_taken": canon_report.actions_taken,
                    "conflicts": canon_report.conflicts,
                },
            }

        # Check if header already promoted (has Code column)
        # P0-2: Skip duplicate normalization to avoid losing data rows
        columns_lower = [str(c).lower() for c in df.columns]
        has_code_column = any("code" in c for c in columns_lower)

        if has_code_column:
            # Header already promoted; use role-based exclude (ROLE_CODE + LABEL)
            roles_ctx = {
                "table_id": (table_context or {}).get("table_id", ""),
                "heading": heading or "",
            }
            roles, _, evidence = infer_column_roles(df, header_row=0, context=roles_ctx)
            code_cols_list = [c for c, r in roles.items() if r == ROLE_CODE]
            code_col = code_cols_list[0] if code_cols_list else None
            skip_cols = set(get_columns_to_exclude_from_sum(roles, include_note=True))
            cur_col, prior_col = ColumnDetector.detect_financial_columns_advanced(df)
            note_col = ColumnDetector.detect_note_column(df)
            if note_col and note_col not in skip_cols:
                skip_cols.add(note_col)
            if cur_col and prior_col:
                candidate_columns = [c for c in [cur_col, prior_col] if c in df.columns]
            else:
                candidate_columns = [c for c in df.columns if c not in skip_cols]
            num_evidence = compute_numeric_evidence_score(df, candidate_columns)
            metadata = {
                "code_column": code_col,
                "code_columns": code_cols_list,
                "current_year_column": cur_col,
                "prior_year_column": prior_col,
                "header_row_idx": -1,
                "normalization_applied": False,
                "note_column": note_col,
                "numeric_parse_rate": num_evidence["numeric_parse_rate"],
                "numeric_cell_ratio": num_evidence["numeric_cell_ratio"],
                "numeric_col_candidates": num_evidence["numeric_col_candidates"],
                "numeric_evidence_score": num_evidence["numeric_evidence_score"],
                **canon_meta,
            }
            logger.info(
                "table numeric_evidence_score=%.3f (has_code_column path)",
                num_evidence["numeric_evidence_score"],
            )
            context = getattr(self, "context", None)
            if context is not None and hasattr(
                context, "set_last_normalization_metadata"
            ):
                context.set_last_normalization_metadata(metadata)
            return df, metadata

        # Otherwise, normalize (header not yet promoted)
        try:
            normalized_df, metadata = TableNormalizer.normalize_table(df, heading)
            code_col_meta = metadata.get("detected_code_column")
            code_cols_meta = (
                TableNormalizer._detect_code_columns_with_synonyms(normalized_df)
                if normalized_df is not None and not normalized_df.empty
                else []
            )
            enriched_metadata: Dict[str, Any] = {
                "code_column": code_col_meta,
                "code_columns": code_cols_meta,
                "current_year_column": metadata.get("detected_cur_col"),
                "prior_year_column": metadata.get("detected_prior_col"),
                "header_row_idx": metadata.get("header_row_idx"),
                "normalization_applied": True,
                "note_column": (
                    ColumnDetector.detect_note_column(normalized_df)
                    if normalized_df is not None and not normalized_df.empty
                    else None
                ),
                **canon_meta,
            }
            # Propagate B1/B4 flags for observability if present.
            for key in [
                "dedup_period_columns_applied",
                "duplicated_period_groups",
                "dedup_conflicts",
                "suspicious_wide_table",
                "suspicious_wide_table_reasons",
                "misalignment_suspected",
                "misalignment_reasons",
                "normalized_columns",
            ]:
                if key in metadata:
                    enriched_metadata[key] = metadata[key]

            cur_meta = enriched_metadata.get("current_year_column")
            prior_meta = enriched_metadata.get("prior_year_column")
            code_cols_meta = enriched_metadata.get("code_columns") or []
            note_meta = enriched_metadata.get("note_column")
            skip_cols = set(code_cols_meta)
            if enriched_metadata.get("code_column"):
                skip_cols.add(enriched_metadata["code_column"])
            if note_meta:
                skip_cols.add(note_meta)
            if cur_meta and prior_meta and normalized_df is not None:
                candidate_columns = [
                    c for c in [cur_meta, prior_meta] if c in normalized_df.columns
                ]
            else:
                candidate_columns = (
                    [c for c in normalized_df.columns if c not in skip_cols]
                    if normalized_df is not None
                    else []
                )
            num_evidence = compute_numeric_evidence_score(
                normalized_df if normalized_df is not None else df,
                candidate_columns,
            )
            enriched_metadata["numeric_parse_rate"] = num_evidence["numeric_parse_rate"]
            enriched_metadata["numeric_cell_ratio"] = num_evidence["numeric_cell_ratio"]
            enriched_metadata["numeric_col_candidates"] = num_evidence[
                "numeric_col_candidates"
            ]
            enriched_metadata["numeric_evidence_score"] = num_evidence[
                "numeric_evidence_score"
            ]
            logger.info(
                "table numeric_evidence_score=%.3f (normalize path)",
                num_evidence["numeric_evidence_score"],
            )

            context = getattr(self, "context", None)
            if context is not None and hasattr(
                context, "set_last_normalization_metadata"
            ):
                context.set_last_normalization_metadata(enriched_metadata)

            return normalized_df, enriched_metadata
        except Exception as e:
            # If normalization fails, return original DataFrame with empty metadata
            # Validators can fall back to their existing detection logic
            fallback_metadata: Dict[str, Any] = {
                "code_column": None,
                "code_columns": [],
                "current_year_column": None,
                "prior_year_column": None,
                "header_row_idx": None,
                "normalization_applied": False,
                "normalization_error": str(e),
                "note_column": ColumnDetector.detect_note_column(df),
                **canon_meta,
            }
            context = getattr(self, "context", None)
            if context is not None and hasattr(
                context, "set_last_normalization_metadata"
            ):
                context.set_last_normalization_metadata(fallback_metadata)
            return df, fallback_metadata

    def _normalize_code(self, code: str) -> str:
        """
        Normalize account code for consistent processing.

        Pre-SCRUM-9 baseline: Strips dots and hyphens for consistent matching.
        This preserves leading zeros and alpha characters but removes separators.

        Args:
            code: Raw code string

        Returns:
            str: Normalized code (strips dots/hyphens, preserves leading zeros and alphanumeric)
        """
        import re

        s = str(code).strip()
        # Remove formatting characters, preserve alphanumeric including leading zeros
        s = (
            s.replace("_", "")
            .replace("**", "")
            .replace("\u2212", "-")
            .replace("–", "-")
        )
        # Pre-SCRUM-9: Strip dots and hyphens (baseline behavior)
        # This ensures consistent matching: "V.01" -> "V01", "A-1" -> "A1"
        s = re.sub(r"[^0-9A-Za-z()]", "", s)
        return s.upper()

    def _preserve_code_column_as_string(
        self, df: pd.DataFrame, code_col_name: str
    ) -> pd.DataFrame:
        """
        P0-R3: Ensure Code column remains as string type to preserve leading zeros.

        Args:
            df: DataFrame with Code column
            code_col_name: Name of the Code column

        Returns:
            pd.DataFrame: DataFrame with Code column as string type
        """
        df = df.copy()
        if code_col_name in df.columns:
            # Force Code column to be object (string) type
            df[code_col_name] = df[code_col_name].astype(str)
        return df

    def _detect_code_column(self, df: pd.DataFrame) -> Optional[str]:
        """
        Detect first Code column (backward-compatible single-column API).

        Uses role-based inference (ROLE_CODE); never used for sum/compare/CY-PY.

        Returns:
            Optional[str]: First detected code column name or None
        """
        code_list = self._detect_code_columns(df)
        return code_list[0] if code_list else None

    def _detect_code_columns(self, df: pd.DataFrame) -> List[str]:
        """
        Detect ALL code-like columns (Code, Code.1, Code.2, synonyms).

        Uses infer_column_roles; ROLE_CODE columns are excluded from sum/total/compare.

        Args:
            df: DataFrame to detect columns in

        Returns:
            List[str]: All detected code column names, in original column order.
        """
        if df.empty:
            return []
        roles_ctx = self._get_roles_context()
        roles, _, _ = infer_column_roles(df, header_row=0, context=roles_ctx)
        return [c for c, r in roles.items() if r == ROLE_CODE]

    def _convert_to_numeric_df(self, df: pd.DataFrame) -> pd.DataFrame:
        """
        Convert entire DataFrame to numeric values.

        Args:
            df: Input DataFrame

        Returns:
            pd.DataFrame: DataFrame with numeric conversion applied
        """
        df_numeric = df.astype(object).map(normalize_numeric_column)
        # Ensure numeric dtype (avoid object/string columns holding numeric strings)
        return df_numeric.apply(pd.to_numeric, errors="coerce")

    def _convert_to_numeric_df_excluding_code(
        self,
        df: pd.DataFrame,
        code_col: Optional[str] = None,
        code_cols: Optional[Sequence[str]] = None,
    ) -> pd.DataFrame:
        """
        Convert DataFrame to numeric, excluding all code-like columns.

        Args:
            df: Input DataFrame
            code_col: Deprecated single column; used only if code_cols is None
            code_cols: All code column names to exclude; if None, derived from code_col or _detect_code_columns

        Returns:
            pd.DataFrame: Copy with numeric conversion applied except to code_cols
        """
        import logging

        logger = logging.getLogger(__name__)
        exclude: List[str] = []
        if code_cols is not None:
            exclude = list(code_cols)
        elif code_col is not None:
            exclude = [code_col]
        else:
            roles_ctx = self._get_roles_context()
            _, _, _, exclude = infer_column_roles_and_exclude(
                df, header_row=0, context=roles_ctx
            )
        df_numeric = df.copy()
        for col in df_numeric.columns:
            if col in exclude:
                continue
            normalized = df_numeric[col].astype(object).map(normalize_numeric_column)
            # Force numeric dtype; non-numeric values become NaN
            df_numeric[col] = pd.to_numeric(normalized, errors="coerce")
        if exclude:
            logger.debug(
                "Excluding code columns from numeric normalization: %s",
                exclude,
            )
        return df_numeric

    def _validate_code_format(self, code: str) -> bool:
        """
        Validate account code format (digits optionally followed by letter).

        Args:
            code: Code to validate

        Returns:
            bool: True if code format is valid
        """
        import re

        return bool(re.match(r"^[0-9]+[A-Z]?$", code))

    def _detect_total_rows(
        self,
        df: pd.DataFrame,
        code_col: Optional[str] = None,
        code_cols: Optional[Sequence[str]] = None,
    ) -> List[Tuple[int, str]]:
        """
        Detect all total/subtotal rows in DataFrame using RowClassifier.

        When code_col or code_cols is provided, those columns are excluded from numeric checks.

        Returns:
            List of (row_index, row_type) tuples where row_type is 'subtotal', 'total', or 'grand_total'
        """
        from ...utils.row_classifier import RowClassifier, RowType

        if df.empty:
            return []

        if code_cols is not None:
            exclude = set(code_cols)
        elif code_col is not None:
            exclude = {code_col}
        else:
            roles_ctx = self._get_roles_context()
            _, _, _, exclude_list = infer_column_roles_and_exclude(
                df, header_row=0, context=roles_ctx
            )
            exclude = set(exclude_list)
        total_rows = []
        row_types = RowClassifier.classify_rows(df)

        for idx, row_type in enumerate(row_types):
            if row_type in (RowType.TOTAL, RowType.SUBTOTAL):
                # Additional validation: check if row has significant numeric values
                if self._validate_dataframe_bounds(df, idx, 0):
                    row = df.iloc[idx]
                    numeric_vals = []
                    for col in row.index:
                        if col in exclude:
                            continue
                        cell = row[col]
                        if pd.notna(cell):
                            numeric_vals.append(normalize_numeric_column(cell))
                    # Relaxed: require at least 1 numeric value (was any(...))
                    # This helps catch total rows that might have been missed
                    if any(not pd.isna(v) and abs(v) > 0.01 for v in numeric_vals):
                        # Determine if grand total (usually last total row)
                        row_text = " ".join(
                            str(cell).lower() for cell in row if pd.notna(cell)
                        )
                        # Expanded keyword matching for grand total detection
                        grand_total_keywords = [
                            "grand",
                            "total",
                            "tổng cộng",
                            "tổng số",
                            "final total",
                            "tổng cuối",
                            "net total",
                            "balance",
                            "ending balance",
                            "closing balance",
                            "số dư cuối",
                            "carried forward",
                            "brought forward",
                        ]
                        if idx == len(df) - 1 and any(
                            k in row_text for k in grand_total_keywords
                        ):
                            total_rows.append((idx, "grand_total"))
                        elif row_type == RowType.SUBTOTAL:
                            total_rows.append((idx, "subtotal"))
                        else:
                            total_rows.append((idx, "total"))

        return total_rows

    def _set_total_row_metadata_on_context(
        self,
        total_row_idx: Optional[int],
        method: str,
        exclude_columns: Sequence[str],
        candidate_indices: Optional[Sequence[int]] = None,
        *,
        totals_candidates_found: Optional[int] = None,
        totals_equations_solved: Optional[int] = None,
        tolerance_used: Optional[Any] = None,
    ) -> None:
        """
        Helper to record total-row selection metadata on the AuditContext for observability.

        Phase 5: Adds totals_candidates_found, totals_equations_solved, tolerance_used.
        """
        ctx = getattr(self, "context", None)
        if ctx is None or not hasattr(ctx, "set_last_total_row_metadata"):
            return
        metadata: Dict[str, Any] = {
            "total_row_idx": total_row_idx,
            "method": method,
            "exclude_columns": list(exclude_columns or []),
        }
        if candidate_indices is not None:
            metadata["candidate_indices"] = list(candidate_indices)
        if totals_candidates_found is not None:
            metadata["totals_candidates_found"] = totals_candidates_found
        if totals_equations_solved is not None:
            metadata["totals_equations_solved"] = totals_equations_solved
        if tolerance_used is not None:
            metadata["tolerance_used"] = tolerance_used
        ctx.set_last_total_row_metadata(metadata)

    def _find_total_row(
        self,
        df: pd.DataFrame,
        code_col: Optional[str] = None,
        code_cols: Optional[Sequence[str]] = None,
    ) -> Optional[int]:
        """
        Find the total row using heuristics.

        Enhanced to use _detect_total_rows() when possible, falls back to original logic.
        When code_col or code_cols is provided, those columns are excluded from numeric checks.

        Args:
            df: DataFrame to search
            code_col: Deprecated single column; used only if code_cols is None
            code_cols: All code column names to exclude from numeric conversion in fallback

        Returns:
            int: Index of total row, or None if not found
        """
        flags = get_feature_flags()
        selection_method = "none"
        if code_cols is not None:
            exclude_list = list(code_cols)
        elif code_col is not None:
            exclude_list = [code_col]
        else:
            roles_ctx = self._get_roles_context()
            _, _, _, exclude_list = infer_column_roles_and_exclude(
                df, header_row=0, context=roles_ctx
            )
        exclude = set(exclude_list)
        # Try using RowClassifier-based detection first
        detected_totals = self._detect_total_rows(df, code_cols=exclude_list)
        if detected_totals:
            if flags.get("tighten_total_row_keywords", False):
                # Prefer grand_total > total > subtotal; within type take max(idx)
                priority_order = ("grand_total", "total", "subtotal")
                by_type: Dict[str, List[int]] = {}
                for row_idx, row_type in detected_totals:
                    by_type.setdefault(row_type, []).append(row_idx)
                idx = None
                for p in priority_order:
                    if p in by_type and by_type[p]:
                        idx = max(by_type[p])
                        break
                if idx is None:
                    idx = detected_totals[-1][0]
            else:
                idx = detected_totals[-1][0]
            # P4: Do not choose total row when there are 0 detail rows above it
            if idx > 0:
                selection_method = "row_classifier"
                logger.info(
                    "Total row candidate selected: idx=%s, method=%s, candidates=%s",
                    idx,
                    selection_method,
                    [t[0] for t in detected_totals],
                )
                self._set_total_row_metadata_on_context(
                    idx,
                    selection_method,
                    exclude_list,
                    [t[0] for t in detected_totals],
                    totals_candidates_found=len(detected_totals),
                )
                return idx

        col_types = ColumnDetector.classify_columns(df)
        label_cols = [
            c for c, t in col_types.items() if t in (ColumnType.TEXT, ColumnType.CODE)
        ]
        amount_cols = [
            c
            for c, t in col_types.items()
            if t in (ColumnType.NUMERIC_CY, ColumnType.NUMERIC_PY, ColumnType.OTHER)
        ]

        def _has_detail_rows_above(row_idx: int) -> bool:
            """True if at least one row above row_idx has a non-year-like numeric in amount cols."""
            # If amount_cols is empty, use all columns except label_cols and exclude_cols
            cols_to_check = (
                amount_cols
                if amount_cols
                else [c for c in df.columns if c not in label_cols and c not in exclude]
            )
            for j in range(row_idx):
                for c in cols_to_check:
                    if c in exclude:
                        continue
                    v = normalize_numeric_column(df.iloc[j].get(c, pd.NA))
                    if pd.notna(v) and not is_year_like_value(v):
                        return True
            return False

        def _as_numeric_series(row, exclude_cols: set):
            s = row.astype(object).copy()
            for c in s.index:
                if c in exclude_cols:
                    s[c] = pd.NA
                else:
                    s[c] = normalize_numeric_column(row[c])
            # Force numeric dtype so downstream totals/abs/sum don't operate on object/string
            return pd.to_numeric(s, errors="coerce")

        def _is_numeric_row(row, exclude_cols: set) -> bool:
            ser = _as_numeric_series(row, exclude_cols)
            return bool(ser.notna().any())

        numeric_rows = [
            i for i in range(len(df)) if _is_numeric_row(df.iloc[i], exclude)
        ]
        n = len(df)

        total_keywords = [
            "total",
            "grand total",
            "subtotal",
            "tổng",
            "tổng cộng",
            "cộng",
            "net",
            "net total",
            "tổng số",
            "tổng hợp",
            "tổng kết",
            "cộng lại",
            "tổng thuần",
            "tổng cộng cuối",
            "final total",
            "tổng cuối",
            # Additional financial statement total indicators
            "balance",
            "ending balance",
            "closing balance",
            "carrying amount",
            "carried forward",
            "brought forward",
            "số dư",
            "số dư cuối",
            "số dư đầu",
            "mang sang",
            "chuyển sang",
        ]
        keyword_candidates: List[int] = []
        for i in range(len(df)):
            row = df.iloc[i]
            row_text = " ".join(str(cell).lower() for cell in row if pd.notna(cell))
            if not any(k in row_text for k in total_keywords):
                continue
            numeric_vals = []
            for col in row.index:
                if col in exclude:
                    continue
                v = normalize_numeric_column(row[col])
                if pd.notna(v):
                    numeric_vals.append(float(v))
            if not any(abs(v) > 0.01 for v in numeric_vals):
                continue
            keyword_candidates.append(i)
        if keyword_candidates:

            def _numeric_below(idx: int) -> int:
                return sum(1 for j in numeric_rows if j > idx)

            passing = []
            for i in keyword_candidates:
                if i == 0 or not _has_detail_rows_above(i):
                    continue
                in_top_half = i < n // 2
                below = _numeric_below(i)
                if in_top_half and below > TOTALS_GUARDRAIL_NUMERIC_BELOW:
                    continue
                passing.append((i, n - 1 - i, below))
            if passing:
                best = max(passing, key=lambda x: (x[1], -x[2]))
                idx = best[0]
                logger.info(
                    "Total row candidate selected: idx=%s, method=keyword_total_row, candidates=%s",
                    idx,
                    keyword_candidates,
                )
                self._set_total_row_metadata_on_context(
                    idx,
                    "keyword_total_row",
                    exclude_list,
                    keyword_candidates,
                    totals_candidates_found=len(keyword_candidates),
                )
                return idx

        rule_b_candidates: List[int] = []
        for i in range(len(df)):
            row = df.iloc[i]
            label_blank = True
            for c in label_cols:
                cell = row.get(c, pd.NA)
                if pd.notna(cell) and str(cell).strip():
                    label_blank = False
                    break
            if not label_blank or not amount_cols:
                continue
            has_numeric = False
            for c in amount_cols:
                v = normalize_numeric_column(row.get(c, pd.NA))
                if pd.notna(v) and abs(float(v)) > 0.01:
                    has_numeric = True
                    break
            if has_numeric:
                rule_b_candidates.append(i)
        if rule_b_candidates:
            idx = rule_b_candidates[-1]
            if idx > 0 and _has_detail_rows_above(idx):
                in_top_half = idx < n // 2
                numeric_below = sum(1 for j in numeric_rows if j > idx)
                if not (in_top_half and numeric_below > TOTALS_GUARDRAIL_NUMERIC_BELOW):
                    logger.info(
                        "Total row candidate selected: idx=%s, method=rule_b_blank_label, candidates=%s",
                        idx,
                        rule_b_candidates,
                    )
                    self._set_total_row_metadata_on_context(
                        idx,
                        "rule_b_blank_label",
                        exclude_list,
                        rule_b_candidates,
                        totals_candidates_found=len(rule_b_candidates),
                    )
                    return idx

        # Rule C: sum-of-previous with configurable abs/rel tolerance; require ≥ min_cols_pct columns
        # Relaxed: For tables with few columns, reduce min_equations threshold

        if flags.get("safe_total_row_selection", True):
            # When no heuristic matched, do not guess a total row (safe behavior)
            if not keyword_candidates and not rule_b_candidates:
                logger.info(
                    "Total row: no keyword/rule_b candidates; returning None (safe_total_row_selection)"
                )
                return None
            # Last resort: try to find a reasonable total row candidate
            # Look for rows in bottom section with numeric values
            fallback_candidates: List[int] = []  # Initialize for logging
            relaxed_candidates: List[int] = []  # Initialize for logging
            if numeric_rows:
                # Expanded: Consider bottom 50% of rows as potential totals (was 30%)
                bottom_start = max(0, len(df) - max(3, len(df) // 2))
                # First pass: prefer rows with detail rows above
                fallback_candidates_with_details = [
                    i
                    for i in numeric_rows
                    if i >= bottom_start and _has_detail_rows_above(i)
                ]
                # Second pass: if no candidates with details, relax requirement for last few rows
                if not fallback_candidates_with_details:
                    # For very bottom rows (last 20%), allow even without detail rows above
                    very_bottom_start = max(0, len(df) - max(2, len(df) // 5))
                    fallback_candidates_with_details = [
                        i for i in numeric_rows if i >= very_bottom_start
                    ]

                fallback_candidates = fallback_candidates_with_details
                if fallback_candidates:
                    # Prefer rows with more numeric values and better position
                    best_fallback = None
                    best_score: float = -1.0
                    # If amount_cols is empty, use all columns except label_cols and exclude_cols
                    candidate_cols = (
                        amount_cols
                        if amount_cols
                        else [
                            c
                            for c in df.columns
                            if c not in label_cols and c not in exclude
                        ]
                    )
                    # Fallback: if candidate_cols is empty (all columns are labels/excluded),
                    # use all columns except exclude only (allow label columns to be checked)
                    if not candidate_cols:
                        candidate_cols = [c for c in df.columns if c not in exclude]
                        logger.info(
                            "safe_fallback_last_numeric: candidate_cols was empty, falling back to all columns except exclude: %s",
                            (
                                candidate_cols[:10]
                                if len(candidate_cols) > 10
                                else candidate_cols
                            ),
                        )
                    logger.info(
                        "safe_fallback_last_numeric: Evaluating %s candidates with candidate_cols=%s (amount_cols empty: %s)",
                        len(fallback_candidates),
                        (
                            candidate_cols[:10]
                            if len(candidate_cols) > 10
                            else candidate_cols
                        ),
                        len(amount_cols) == 0,
                    )
                    for i in fallback_candidates:
                        row = df.iloc[i]
                        numeric_count = sum(
                            1
                            for c in candidate_cols
                            if c not in exclude
                            and pd.notna(normalize_numeric_column(row.get(c, pd.NA)))
                            and abs(float(normalize_numeric_column(row.get(c, pd.NA))))
                            > 0.01
                        )
                        # Score: numeric_count * 100 + position_score (prefer later rows)
                        # Position score: (len(df) - i) / len(df) * 50
                        position_score = (
                            ((len(df) - i) / max(len(df), 1)) * 50 if len(df) > 0 else 0
                        )
                        score = numeric_count * 100 + position_score
                        # Bonus if has detail rows above
                        has_details_above = _has_detail_rows_above(i)
                        if has_details_above:
                            score += 25
                        logger.info(
                            "safe_fallback_last_numeric candidate idx=%s: numeric_count=%s, position_score=%.1f, has_details_above=%s, total_score=%.1f",
                            i,
                            numeric_count,
                            position_score,
                            has_details_above,
                            score,
                        )
                        if score > best_score:
                            best_score = score
                            best_fallback = i
                    logger.info(
                        "safe_fallback_last_numeric: best_fallback=%s, best_score=%.1f",
                        best_fallback,
                        best_score,
                    )
                    if best_fallback is not None:
                        row = df.iloc[best_fallback]
                        numeric_count = sum(
                            1
                            for c in candidate_cols
                            if c not in exclude
                            and pd.notna(normalize_numeric_column(row.get(c, pd.NA)))
                            and abs(float(normalize_numeric_column(row.get(c, pd.NA))))
                            > 0.01
                        )
                        if numeric_count >= 1:
                            logger.info(
                                "Total row fallback selected: idx=%s, method=safe_fallback_last_numeric, numeric_count=%s, score=%.1f",
                                best_fallback,
                                numeric_count,
                                best_score,
                            )
                            self._set_total_row_metadata_on_context(
                                best_fallback,
                                "safe_fallback_last_numeric",
                                exclude_list,
                                fallback_candidates,
                                totals_candidates_found=len(fallback_candidates),
                            )
                            return best_fallback

                # Third pass: if still no candidates in bottom section, try entire table with relaxed conditions
                # This handles edge cases where total row might be in middle/upper section
                if not fallback_candidates:
                    # For very small tables (< 5 rows), consider all numeric rows
                    # For larger tables, prefer rows in lower 70% of table
                    if len(df) < 5:
                        relaxed_candidates = numeric_rows
                    else:
                        relaxed_start = max(0, len(df) // 3)  # Lower 70% of table
                        relaxed_candidates = [
                            i for i in numeric_rows if i >= relaxed_start
                        ]

                    if relaxed_candidates:
                        # Score candidates: prefer more numeric values and later position
                        best_relaxed = None
                        best_relaxed_score: float = -1.0
                        # If amount_cols is empty, use all columns except label_cols and exclude_cols
                        candidate_cols = (
                            amount_cols
                            if amount_cols
                            else [
                                c
                                for c in df.columns
                                if c not in label_cols and c not in exclude
                            ]
                        )
                        # Fallback: if candidate_cols is empty (all columns are labels/excluded),
                        # use all columns except exclude only (allow label columns to be checked)
                        if not candidate_cols:
                            candidate_cols = [c for c in df.columns if c not in exclude]
                            logger.info(
                                "safe_fallback_relaxed_search: candidate_cols was empty, falling back to all columns except exclude: %s",
                                (
                                    candidate_cols[:10]
                                    if len(candidate_cols) > 10
                                    else candidate_cols
                                ),
                            )
                        logger.info(
                            "safe_fallback_relaxed_search: Evaluating %s candidates with candidate_cols=%s (amount_cols empty: %s)",
                            len(relaxed_candidates),
                            (
                                candidate_cols[:10]
                                if len(candidate_cols) > 10
                                else candidate_cols
                            ),
                            len(amount_cols) == 0,
                        )
                        for i in relaxed_candidates:
                            row = df.iloc[i]
                            numeric_count = sum(
                                1
                                for c in candidate_cols
                                if c not in exclude
                                and pd.notna(
                                    normalize_numeric_column(row.get(c, pd.NA))
                                )
                                and abs(
                                    float(normalize_numeric_column(row.get(c, pd.NA)))
                                )
                                > 0.01
                            )
                            logger.info(
                                "safe_fallback_relaxed_search candidate idx=%s: numeric_count=%s",
                                i,
                                numeric_count,
                            )
                            if numeric_count >= 1:
                                # Score: numeric_count * 100 + position_score (prefer later rows)
                                position_score = (
                                    ((len(df) - i) / max(len(df), 1)) * 50
                                    if len(df) > 0
                                    else 0
                                )
                                score = numeric_count * 100 + position_score
                                # Bonus if has detail rows above
                                has_details_above = _has_detail_rows_above(i)
                                if has_details_above:
                                    score += 25
                                # Bonus if in bottom section
                                in_bottom = i >= bottom_start
                                if in_bottom:
                                    score += 15
                                logger.info(
                                    "safe_fallback_relaxed_search candidate idx=%s: numeric_count=%s, position_score=%.1f, has_details_above=%s, in_bottom=%s, total_score=%.1f",
                                    i,
                                    numeric_count,
                                    position_score,
                                    has_details_above,
                                    in_bottom,
                                    score,
                                )
                                if score > best_relaxed_score:
                                    best_relaxed_score = score
                                    best_relaxed = i

                        logger.info(
                            "safe_fallback_relaxed_search: best_relaxed=%s, best_relaxed_score=%.1f",
                            best_relaxed,
                            best_relaxed_score,
                        )
                        if best_relaxed is not None:
                            # Use candidate_cols if amount_cols is empty
                            final_candidate_cols = (
                                amount_cols
                                if amount_cols
                                else [
                                    c
                                    for c in df.columns
                                    if c not in label_cols and c not in exclude
                                ]
                            )
                            logger.info(
                                "Total row relaxed fallback selected: idx=%s, method=safe_fallback_relaxed_search, numeric_count=%s, score=%.1f",
                                best_relaxed,
                                sum(
                                    1
                                    for c in final_candidate_cols
                                    if c not in exclude
                                    and pd.notna(
                                        normalize_numeric_column(
                                            df.iloc[best_relaxed].get(c, pd.NA)
                                        )
                                    )
                                    and abs(
                                        float(
                                            normalize_numeric_column(
                                                df.iloc[best_relaxed].get(c, pd.NA)
                                            )
                                        )
                                    )
                                    > 0.01
                                ),
                                best_relaxed_score,
                            )
                            self._set_total_row_metadata_on_context(
                                best_relaxed,
                                "safe_fallback_relaxed_search",
                                exclude_list,
                                relaxed_candidates,
                                totals_candidates_found=len(relaxed_candidates),
                            )
                            return best_relaxed

            # If still no match, return None
            # Enhanced logging for debugging safe_total_row_selection_no_match cases
            logger.warning(
                "Total row not found after all detection methods: "
                "detected_totals=%s, keyword_candidates=%s, rule_b_candidates=%s, "
                "rule_b_candidates=%s, numeric_rows=%s, fallback_candidates=%s, "
                "relaxed_candidates=%s, table_size=%s, label_cols=%s, amount_cols=%s, "
                "exclude_cols=%s",
                detected_totals,
                keyword_candidates,
                rule_b_candidates,
                (
                    numeric_rows[:10]
                    if numeric_rows and len(numeric_rows) > 10
                    else (numeric_rows if numeric_rows else [])
                ),
                fallback_candidates,
                relaxed_candidates,
                len(df),
                (
                    label_cols[:5]
                    if label_cols and len(label_cols) > 5
                    else (label_cols if label_cols else [])
                ),
                (
                    amount_cols[:5]
                    if amount_cols and len(amount_cols) > 5
                    else (amount_cols if amount_cols else [])
                ),
                (
                    exclude_list[:5]
                    if exclude_list and len(exclude_list) > 5
                    else (exclude_list if exclude_list else [])
                ),
            )
            # Log sample rows for pattern analysis
            if len(df) > 0:
                sample_indices = [0, len(df) // 2, len(df) - 1] if len(df) >= 3 else [0]
                for idx in sample_indices:
                    row = df.iloc[idx]
                    row_sample = {}
                    for col in list(row.index)[:5]:  # First 5 columns
                        val = row.get(col, pd.NA)
                        if pd.notna(val):
                            row_sample[col] = str(val)[:50]  # Truncate long values
                    logger.debug(
                        "Sample row idx=%s: %s",
                        idx,
                        row_sample,
                    )
            self._set_total_row_metadata_on_context(
                None, "safe_total_row_selection_no_match", exclude_list, []
            )
            return None

        if not numeric_rows:
            self._set_total_row_metadata_on_context(
                None, "legacy_no_numeric_rows", exclude_list, []
            )
            return None

        def _is_empty_row(row) -> bool:
            def _strip_text(x):
                s = str(x).strip()
                s = s.replace("-", "").replace("–", "").replace("—", "")
                s = s.replace("(", "").replace(")", "").replace(",", "")
                return s.strip()

            has_text = any(_strip_text(c) != "" for c in row)
            has_num = _is_numeric_row(row, exclude)
            return (not has_text) and (not has_num)

        bottom_size = max(TOTALS_LEGACY_BOTTOM_N, len(numeric_rows) // 2)
        bottom_pool = numeric_rows[-bottom_size:] if numeric_rows else []
        for i in reversed(bottom_pool):
            prev_empty = True
            if i - 1 >= 0:
                prev_empty = _is_empty_row(df.iloc[i - 1])
            if prev_empty:
                selection_method = "legacy_empty_row_heuristic"
                self._set_total_row_metadata_on_context(
                    i, selection_method, exclude_list, numeric_rows
                )
                return i

        idx = numeric_rows[-1]
        selection_method = "legacy_last_numeric_row"
        self._set_total_row_metadata_on_context(
            idx, selection_method, exclude_list, numeric_rows
        )
        return idx

    def _detect_amount_columns(
        self,
        df: pd.DataFrame,
        code_cols: Optional[Sequence[str]] = None,
    ) -> List[str]:
        """
        A2: Detect amount columns (subset of numeric columns that represent monetary amounts).

        Baseline strategy:
        - Use ColumnDetector for (cur, prior) when available.
        - Expand to a contiguous block of period-like columns when > 2 exist.
        - Exclude code-like columns and obvious non-amount numeric columns (rates/percent/maturity/note).
        """
        if df is None or df.empty:
            return []

        exclude = set(code_cols or [])
        cols = list(df.columns)

        # Identify period-like columns by header patterns.
        period_idxs: List[int] = []
        for i, c in enumerate(cols):
            if c in exclude:
                continue
            if ColumnDetector.has_year_pattern(str(c)):
                period_idxs.append(i)

        # Remove obvious non-amount numeric columns by header keywords.
        non_amount_terms = [
            "rate",
            "%",
            "percent",
            "percentage",
            "maturity",
            "days",
            "day",
            "note",
            "notes",
            "thuyết minh",
            "thuyet minh",
        ]

        def _is_non_amount(col_name: str) -> bool:
            s = str(col_name).lower()
            return any(t in s for t in non_amount_terms)

        period_idxs = [i for i in period_idxs if not _is_non_amount(str(cols[i]))]

        if len(period_idxs) >= 3:
            # Expand to contiguous block covering all detected period columns.
            start, end = min(period_idxs), max(period_idxs)
            block = [cols[i] for i in range(start, end + 1) if cols[i] not in exclude]
            block = [c for c in block if not _is_non_amount(str(c))]
            return block

        # Default: try the (cur, prior) pair.
        cur, prior = ColumnDetector.detect_financial_columns_advanced(df)
        picked: List[str] = []
        if cur and cur in cols and cur not in exclude and not _is_non_amount(str(cur)):
            picked.append(cur)
        if (
            prior
            and prior in cols
            and prior not in exclude
            and not _is_non_amount(str(prior))
        ):
            if prior != cur:
                picked.append(prior)
        return picked

    def cross_check_with_BSPL(
        self,
        df: pd.DataFrame,
        cross_ref_marks: List[Dict],
        issues: List[str],
        account_name: str,
        CY_bal: float,
        PY_bal: float,
        CY_row: int,
        CY_col: int,
        gap_row: int,
        gap_col: int,
    ) -> None:
        """
        Cross-check current table values with cached BSPL values.

        Args:
            df: DataFrame containing the table
            cross_ref_marks: List to append cross-reference marks to
            issues: List to append issues to
            account_name: Account name to cross-check
            CY_bal: Current year balance from current table
            PY_bal: Prior year balance from current table
            CY_row: Current year row index
            CY_col: Current year column index
            gap_row: Row gap for prior year position
            gap_col: Column gap for prior year position
        """
        cached_value = cross_check_cache.get(account_name)
        if cached_value is None:
            return  # No cached value to compare against

        BSPL_CY_bal, BSPL_PY_bal = cached_value

        # Calculate differences: Note - BSPL (convention: positive when Note > BSPL)
        diffCB = CY_bal - BSPL_CY_bal
        diffOB = PY_bal - BSPL_PY_bal

        # Ticket 9: Magnitude Sanity Check
        # If the gap between Note and BSPL is astronomically large (e.g. Note is 1B but BSPL is 1M),
        # it's likely a false positive match across sections. Reject the cross-check (do not mark as failed or ok).
        def _is_suspicious_magnitude(bal_note: float, bal_bspl: float) -> bool:
            if abs(bal_bspl) > 1000 and abs(bal_note) > 1000:
                if (
                    abs(bal_note) > abs(bal_bspl) * 10
                    or abs(bal_bspl) > abs(bal_note) * 10
                ):
                    return True
            return False

        if _is_suspicious_magnitude(CY_bal, BSPL_CY_bal) or _is_suspicious_magnitude(
            PY_bal, BSPL_PY_bal
        ):
            logger.debug(f"Cross-check blocked by magnitude check for {account_name}")
            return

        # Ticket 9: Section Constraint Validation (Whitelist check)
        # Prevent "Chi phí trả trước" (Short-term) checking against "Chi phí trả trước" (Long-term)
        def _validate_section_alignment(target_acct: str, current_heading: str) -> bool:
            if not current_heading:
                return True

            heading_lower = current_heading.lower()
            acct_lower = target_acct.lower()

            # Simple whitelist token overlap mapping
            # Key: BSPL account, Value: Valid tokens that should exist in the Note heading
            # If the account requires specific note headings, it must match at least one token
            whitelist_map = {
                "tài sản cố định hữu hình": ["hữu hình"],
                "tài sản cố định vô hình": ["vô hình"],
                "bất động sản đầu tư": ["bất động sản"],
                "chi phí trả trước dài hạn": ["dài hạn"],
                "chi phí trả trước ngắn hạn": ["ngắn hạn"],
                "doanh thu chưa thực hiện dài hạn": ["dài hạn"],
                "doanh thu chưa thực hiện ngắn hạn": ["ngắn hạn"],
            }

            for acct, required_tokens in whitelist_map.items():
                if acct in acct_lower:
                    if not any(token in heading_lower for token in required_tokens):
                        return False  # Fails section constraint

            return True

        # Extract table heading from dataframe context if injected by higher level
        current_heading = df.attrs.get("heading", "")
        if not _validate_section_alignment(account_name, current_heading):
            logger.debug(
                f"Cross-check blocked by section constraint alignment check for {account_name}"
            )
            return

        # P2-L2: Relaxed cross-check for minor diffs (allow +/- 1.0 for rounding)
        TOLERANCE = 1.0
        is_okCB = abs(diffCB) <= TOLERANCE
        is_okOB = abs(diffOB) <= TOLERANCE

        # Adjust position for special cases
        adjusted_CY_row = CY_row
        adjusted_CY_col = CY_col

        if (
            account_name in TABLES_NEED_CHECK_SEPARATELY
            or account_name in VALID_CODES
            or account_name
            in ["50", "construction in progress", "long-term prepaid expenses"]
            or "revenue" in account_name
        ):
            adjusted_CY_row = CY_row - 1
            adjusted_CY_col = len(df.columns)

        # Create cross-reference marks for current year
        # Always include comment for traceability (tests/UI need it)
        commentCB = (
            f"BSPL = {BSPL_CY_bal:,.2f}, Note = {CY_bal:,.2f}, Sai lệch = {diffCB:,.0f}"
        )
        cross_ref_marks.append(
            {
                "row": adjusted_CY_row,
                "col": adjusted_CY_col,
                "ok": is_okCB,
                "comment": commentCB,  # Always include comment
                "rule_id": "CROSS_REF_BSPL_CY",
            }
        )
        if not is_okCB:
            issues.append(commentCB)

        # Create cross-reference marks for prior year
        commentOB = (
            f"BSPL = {BSPL_PY_bal:,.2f}, Note = {PY_bal:,.2f}, Sai lệch = {diffOB:,.0f}"
        )
        cross_ref_marks.append(
            {
                "row": adjusted_CY_row - gap_row,
                "col": adjusted_CY_col - gap_col,
                "ok": is_okOB,
                "comment": commentOB,  # Always include comment
                "rule_id": "CROSS_REF_BSPL_PY",
            }
        )
        if not is_okOB:
            issues.append(commentOB)

        # Track that this account was cross-checked (tests rely on this global).
        cross_check_marks.add(account_name)

    def _calculate_severity(
        self, rule_id: str, diff_abs: float = 0.0, is_skipped: bool = False
    ) -> str:
        """
        SCRUM-7: Calculate severity based on rule criticality and magnitude.

        Args:
            rule_id: Rule identifier
            diff_abs: Absolute difference magnitude
            is_skipped: Whether this finding is from a heuristic skip

        Returns:
            str: HIGH, MEDIUM, or LOW
        """
        # 1. Base criticality from taxonomy (now a 3-tuple with root_cause)
        taxonomy_entry = RULE_TAXONOMY.get(
            rule_id, ("Unknown", RuleCriticality.MEDIUM, "general")
        )
        family = taxonomy_entry[0]
        base_crit = taxonomy_entry[1]

        # 2. Adjust based on heuristics
        if is_skipped:
            return "LOW"

        # 3. Adjust based on magnitude for Math/Cross-Check rules
        if family in ["FS Casting", "Cross-Check"]:
            if diff_abs >= ScoringConfig.DIFF_THRESHOLD_CRITICAL:
                return "HIGH"  # Critical impact
            elif diff_abs >= ScoringConfig.DIFF_THRESHOLD_HIGH:
                return "HIGH"
            elif diff_abs >= ScoringConfig.DIFF_THRESHOLD_MEDIUM:
                return "MEDIUM"
            else:
                return "LOW"

        # 4. Default to base criticality for structural rules
        return base_crit.name

    def _calculate_confidence(
        self,
        rule_id: str,
        is_skipped: bool = False,
        is_heuristic: bool = False,
        context: Optional[Dict] = None,
    ) -> str:
        """
        SCRUM-7: Calculate confidence in the finding.

        Args:
            rule_id: Rule identifier
            is_skipped: Whether finding is a skip/heuristic
            is_heuristic: Whether logic relied on fuzzy matching
            context: Additional context (e.g., column mapping quality)

        Returns:
            str: HIGH, MEDIUM, or LOW
        """
        # Lower confidence for skipping logic or heuristics
        if is_skipped or is_heuristic:
            return "MEDIUM"

        # Default high confidence for explicit math failures
        if rule_id in ["MATH_EQ", "CROSS_CHECK_MISMATCH"]:
            return "HIGH"

        # If we had trouble detecting columns, confidence drops
        if context and context.get("ambiguous_columns"):
            return "LOW"

        return "HIGH"

    def _extract_top_diffs(
        self,
        df: pd.DataFrame,
        cal_col_idx: int,
        formula_col_idx: int,
        diff_col_idx: int,
        top_n: int = 5,
    ) -> List[Dict[str, Any]]:
        """
        SCRUM-7: Extract top N discrepant rows for evidence block.

        Args:
            df: DataFrame with results
            cal_col_idx: Index of calculated value column
            formula_col_idx: Index of Formula/Expected value column
            diff_col_idx: Index of Diff column

        Returns:
            List of dicts with row details
        """
        try:
            # Filter for non-zero diffs
            mask = df.iloc[:, diff_col_idx].abs() > 0.01  # Tolerance
            diff_rows = df[mask].copy()

            if diff_rows.empty:
                return []

            # Sort by absolute diff descending
            diff_rows["_abs_diff"] = diff_rows.iloc[:, diff_col_idx].abs()
            top_rows = diff_rows.sort_values("_abs_diff", ascending=False).head(top_n)

            evidence = []
            for idx, row in top_rows.iterrows():
                # Try to get row label/code (usually col 0 or 1)
                label = str(row.iloc[0]) if len(row) > 0 else f"Row {idx}"
                if len(row) > 1 and len(str(row.iloc[0])) < 5:  # Maybe Code column
                    label = f"{row.iloc[0]} - {row.iloc[1]}"

                evidence.append(
                    {
                        "row_idx": idx,
                        "label": label[:50],  # Truncate
                        "actual": float(row.iloc[cal_col_idx]),
                        "expected": float(row.iloc[formula_col_idx]),
                        "diff": float(row.iloc[diff_col_idx]),
                    }
                )
            return evidence
        except Exception:
            return []  # Fail safe

    def _infer_root_cause(self, rule_id: str, context: Optional[Dict] = None) -> str:
        """
        SCRUM-7 P1: Infer suspected root cause from rule_id and context.

        Args:
            rule_id: Rule identifier
            context: Additional context from validation

        Returns:
            str: Root cause tag (e.g., 'calculation', 'mapping', 'subtotal')
        """
        # Look up in taxonomy
        if rule_id in RULE_TAXONOMY:
            taxonomy_entry = RULE_TAXONOMY[rule_id]
            if len(taxonomy_entry) >= 3:
                return taxonomy_entry[2]  # Root cause tag

        # Infer from context if available
        if context:
            # Subtotal detection
            if context.get("subtotals_detected") or context.get("has_subtotals"):
                return "subtotal"
            # Movement table
            if context.get("is_movement_table"):
                return "movement"
            # Mapping issues
            if context.get("missing_codes") or context.get("unmapped"):
                return "mapping"

        # Default based on rule_id patterns
        if "MATH" in str(rule_id):
            return "calculation"
        if "CROSS" in str(rule_id):
            return "cross_ref"
        if "STRUCT" in str(rule_id) or "HEADER" in str(rule_id):
            return "structure"

        return "general"
