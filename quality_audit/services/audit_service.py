"""
Main audit service orchestrating the entire validation workflow.
"""

import asyncio
import builtins
import importlib.util
import logging
import re
from pathlib import Path
from typing import TYPE_CHECKING, Any, Dict, List, Optional, Tuple

import pandas as pd
from openpyxl import Workbook

from ..config.constants import (
    TABLES_WITHOUT_TOTAL,
)
from ..config.feature_flags import get_feature_flags
from ..core.cache_manager import (
    AuditContext,
    LRUCacheManager,
    cross_check_cache,
    cross_check_marks,
)
from ..core.exceptions import FileProcessingError, SecurityError, ValidationError
from ..core.validators.factory import ValidatorFactory
from ..io import ExcelWriter, FileHandler
from ..io.word_reader import AsyncWordReader, WordReader
from ..utils.skip_classifier import classify_footer_signature
from ..utils.telemetry_collector import TelemetryCollector
from .base_service import BaseService

logger = logging.getLogger(__name__)

_LEGACY_MAIN_MODULE = None

if TYPE_CHECKING:
    from ..core.validators.base_validator import ValidationResult


def _load_legacy_main_module():
    global _LEGACY_MAIN_MODULE
    if _LEGACY_MAIN_MODULE is not None:
        return _LEGACY_MAIN_MODULE
    legacy_path = Path("legacy/main.py")
    spec = importlib.util.spec_from_file_location("legacy_main_runtime", legacy_path)
    module = importlib.util.module_from_spec(spec)
    assert spec is not None and spec.loader is not None
    spec.loader.exec_module(module)
    _LEGACY_MAIN_MODULE = module
    return module


class AuditService(BaseService):
    """
    Main service for orchestrating financial statement auditing.

    Coordinates Word reading, validation, and Excel report generation.
    """

    def __init__(
        self,
        context: Optional[AuditContext] = None,
        cache_manager: Optional[LRUCacheManager] = None,
        word_reader: Optional[WordReader] = None,
        async_word_reader: Optional[AsyncWordReader] = None,
        excel_writer: Optional[ExcelWriter] = None,
        file_handler: Optional[FileHandler] = None,
    ):
        """
        Initialize audit service with dependencies.

        Args:
            context: Audit context with cache and marks (preferred over cache_manager)
            cache_manager: Cache for cross-referencing data (deprecated, use context instead)
            word_reader: Word document reader (sync)
            async_word_reader: Async word document reader for concurrent processing
            excel_writer: Excel report writer
            file_handler: Secure file handler
        """
        # Initialize base service with context
        super().__init__(context=context, cache_manager=cache_manager)

        self.word_reader = word_reader or WordReader()
        self.async_word_reader = async_word_reader
        self.excel_writer = excel_writer or ExcelWriter()
        self.file_handler = file_handler or FileHandler()
        self.telemetry = TelemetryCollector()
        # Compatibility surface: some tests/consumers expect this attribute to exist.
        # Canonical runtime no longer depends on legacy/main.py for correctness.
        class _LegacyEngineShim:
            def validate_table(self, *_args: Any, **_kwargs: Any) -> Any:  # pragma: no cover
                raise NotImplementedError("legacy_engine is a shim for compatibility")

        self.legacy_engine = _LegacyEngineShim()

        # Keep cache_manager for backward compatibility (deprecated)
        self.cache_manager = self.context.cache

    def _reset_run_state(self, word_path: str) -> None:
        """
        Reset all mutable cross-check state at run boundary.

        This includes both context-scoped state and legacy module-level globals
        used by canonical runtime delegation in legacy/main.py.
        """
        # Preferred run-scoped owner
        self.context.clear()
        # Clear run-scoped cache to prevent repeated-run state leaks when reusing
        # the same AuditService/AuditContext instance within a process.
        self.context.cache.clear()
        self.context.current_filename = str(Path(word_path).absolute())

        # Legacy global compatibility
        cross_check_cache.clear()
        cross_check_marks.clear()

        # Canonical runtime still delegates to legacy module, which owns additional
        # module-level globals that must also be reset every run.
        try:
            legacy_main = _load_legacy_main_module()
            legacy_cache = getattr(legacy_main, "BSPL_cross_check_cache", None)
            if isinstance(legacy_cache, dict):
                legacy_cache.clear()

            legacy_marks = getattr(legacy_main, "BSPL_cross_check_mark", None)
            if isinstance(legacy_marks, (list, set, dict)):
                legacy_marks.clear()
        except Exception as exc:  # pragma: no cover - best-effort legacy reset
            logger.debug("Unable to reset legacy cross-check globals: %s", exc)

    def audit_document(self, word_path: str, excel_path: str) -> Dict[str, Any]:
        """
        Execute complete audit workflow.

        Args:
            word_path: Path to Word document
            excel_path: Path to output Excel file

        Returns:
            Dict with audit results and metadata
        """
        try:
            self._reset_run_state(word_path)
            self.telemetry.start_run()

            # Validate inputs with proper error handling
            if not self.file_handler.validate_path(word_path):
                raise SecurityError(f"Invalid or unsafe Word file path: {word_path}")

            # SEC-1: Check for zip bomb
            if not self.file_handler.validate_docx_safety(word_path):
                raise SecurityError(
                    f"Potential Zip Bomb detected or invalid DOCX structure: {word_path}"
                )

            table_heading_pairs = self.word_reader.read_tables_with_headings(word_path)
            if not table_heading_pairs:  # pragma: no cover
                raise ValueError("No tables found in Word document")

            # Strip optional per-table context for report output pairing.
            # Support both 2-tuple (df, heading) and 3-tuple (df, heading, ctx).
            table_heading_pairs_for_report: List[Tuple[pd.DataFrame, Optional[str]]] = []
            for pair in table_heading_pairs:
                if len(pair) >= 2:
                    table_heading_pairs_for_report.append((pair[0], pair[1]))  # type: ignore[index]

            results = self._validate_tables(table_heading_pairs)
            self.telemetry.end_run()
            self._generate_report(
                table_heading_pairs_for_report,
                results,
                excel_path,
                telemetry=self.telemetry,
            )

            return {
                "success": True,
                "tables_processed": len(table_heading_pairs_for_report),
                "results": results,
                "output_path": excel_path,
            }

        except (SecurityError, FileProcessingError, ValidationError) as e:
            # Return error result for known exceptions
            return {
                "success": False,
                "error": str(e),
                "error_type": type(e).__name__,
                "tables_processed": 0,
                "results": [],
                "output_path": None,
            }
        except Exception as e:
            return {
                "success": False,
                "error": f"Unexpected error during audit: {str(e)}",
                "error_type": "QualityAuditError",
                "tables_processed": 0,
                "results": [],
                "output_path": None,
            }

    def _validate_tables(self, table_heading_pairs: List[Tuple]) -> List[Dict]:
        """
        Validate all tables using appropriate validators.

        NON-RUNTIME (canonical mode): this path is retained for experimental/shadow
        workflows only. Production correctness is owned by legacy/main.py via
        audit_document()/process_document_async().

        E2: Includes telemetry tracking for each table validation.

        Args:
            table_heading_pairs: List of (table_df, heading) tuples

        Returns:
            List of validation results
        """
        results: List[Dict] = []
        # Normalize input shape: allow (df, heading) or (df, heading, context)
        normalized_pairs: List[Tuple[pd.DataFrame, Optional[str], Dict]] = []
        for item in table_heading_pairs:
            if not isinstance(item, tuple):
                continue
            if len(item) == 2:
                table, heading = item
                table_context: Dict = {}
            elif len(item) >= 3:
                table, heading, table_context = item[0], item[1], item[2] or {}
            else:
                continue
            normalized_pairs.append((table, heading, table_context))

        # P2-1: Optional pre-build of document-level cash flow registry (run-scoped).
        flags = get_feature_flags()
        if bool(flags.get("cashflow_cross_table_context", False)):
            cashflow_tables = [
                (t, h, ctx)
                for (t, h, ctx) in normalized_pairs
                if "cash flow" in str(h or "").strip().lower()
            ]
            if cashflow_tables:
                self.context.cash_flow_registry = self._build_cf_registry(cashflow_tables)

        # Main validation pass (all tables)
        for idx, (table, heading, table_context) in enumerate(normalized_pairs):
            # E2: Start tracking this table
            self.telemetry.start_table(heading)

            # SCRUM-8: Generate unique, deterministic, and readable table_id
            safe_heading = re.sub(r"[^A-Za-z0-9]", "_", heading or "unknown")
            slug = safe_heading[:50].strip("_")
            if not slug:
                slug = "unnamed"

            table_id = f"tbl_{idx + 1:03d}_{slug}"
            table_id = re.sub(r"[^A-Za-z0-9_]", "_", table_id)

            # Inject table_id (and heading) into table_context so column_roles logs never show empty table_id
            table_context = dict(table_context or {})
            table_context["table_id"] = table_id
            table_context["heading"] = heading or ""

            # Clear per-table observability metadata before validation
            if hasattr(self.context, "set_last_normalization_metadata"):
                self.context.set_last_normalization_metadata(None)
            if hasattr(self.context, "set_last_total_row_metadata"):
                self.context.set_last_total_row_metadata(None)

            # _validate_single_table is now fail-safe and never raises
            result = self._validate_single_table(table, heading, table_context)

            # Observability: mark cross-table usage for cash flow tables when enabled.
            # (CashFlowValidator consumes AuditContext.cash_flow_registry when present.)
            if bool(flags.get("cashflow_cross_table_context", False)) and (
                "cash flow" in str(heading or "").strip().lower()
            ):
                if result.context.get("validator_type") == "CashFlowValidator":
                    result.context["cross_table_used"] = True

            # Merge classification context + table context into result.context for observability
            classification_ctx = self.context.get_last_classification_context() or {}
            primary_type = classification_ctx.get("classifier_primary_type")
            # Normalize classifier_primary_type to stable, human-readable enum names
            # expected by plan/golden tests (e.g. "FS_BALANCE_SHEET"), rather than enum values.
            if isinstance(primary_type, str):
                from ..core.routing.table_type_classifier import TableType

                _map = {
                    TableType.FS_BALANCE_SHEET.value: "FS_BALANCE_SHEET",
                    TableType.FS_INCOME_STATEMENT.value: "FS_INCOME_STATEMENT",
                    TableType.FS_CASH_FLOW.value: "FS_CASH_FLOW",
                    TableType.FS_EQUITY.value: "FS_EQUITY",
                    TableType.TAX_NOTE.value: "TAX_NOTE",
                    TableType.GENERIC_NOTE.value: "GENERIC_NOTE",
                    TableType.UNKNOWN.value: "UNKNOWN",
                }
                primary_type = _map.get(primary_type, primary_type)
            heading_source = (table_context or {}).get("heading_source")
            excluded_columns = result.context.get("excluded_columns", [])
            scan_rows = classification_ctx.get("scan_rows")

            enriched_ctx = {
                "heading": heading or f"Table {idx + 1}",
                "table_index": idx,
                "heading_source": heading_source,
                "heading_confidence": (table_context or {}).get("heading_confidence"),
                "classifier_confidence": classification_ctx.get(
                    "classifier_confidence"
                ),
                "classifier_reason": classification_ctx.get("classifier_reason"),
                "classifier_primary_type": primary_type,
                "scan_rows": scan_rows,
                "validator_type": result.context.get("validator_type"),
                "excluded_columns": excluded_columns,
                "table_shape": table.shape if not table.empty else (0, 0),
            }

            # Phase 6: Merge extraction metadata from table_context (extractor_engine, quality_score, etc.)
            enriched_ctx.update(table_context or {})

            # Shallow-merge to preserve existing keys but prefer more specific values above
            enriched_ctx.update(result.context)

            # Attach normalization/total-row metadata for observability if available.
            normalization_meta = (
                self.context.get_last_normalization_metadata()
                if hasattr(self.context, "get_last_normalization_metadata")
                else None
            ) or {}
            # Prefer total_row_metadata from validator result to avoid cross-table contamination
            total_row_meta = (
                result.context.get("total_row_metadata")
                or (
                    self.context.get_last_total_row_metadata()
                    if hasattr(self.context, "get_last_total_row_metadata")
                    else None
                )
            ) or {}
            if normalization_meta:
                enriched_ctx.setdefault("normalization_metadata", normalization_meta)
            if total_row_meta:
                enriched_ctx.setdefault("total_row_metadata", total_row_meta)

            result.context = enriched_ctx

            # WARN contract: ensure context.reason_code exists and is in WARN_REASON_CODES.
            if (result.status_enum or "") == "WARN":
                from ..config.constants import (
                    WARN_REASON_CODES,
                    WARN_REASON_STRUCTURE_UNDETERMINED,
                )

                rc = (result.context or {}).get("reason_code")
                if rc not in WARN_REASON_CODES:
                    result.context["reason_code"] = WARN_REASON_STRUCTURE_UNDETERMINED

            # Observability: distinguish Validated vs Skipped so skipped tables are not reported as Validated
            rule_id = result.rule_id or ""
            validation_status = (
                "Skipped"
                if rule_id
                in (
                    "SKIPPED_FOOTER_SIGNATURE",
                    "SKIPPED_NO_NUMERIC_EVIDENCE",
                )
                else "Validated"
            )
            result.context["validation_status"] = validation_status
            logger.info(
                "%s table_id=tbl_%03d_%s heading_source=%s "
                "classifier_reason=%s validator_type=%s excluded_columns=%s scan_rows=%s",
                validation_status,
                idx + 1,
                (heading or "unknown"),
                heading_source,
                classification_ctx.get("classifier_reason"),
                result.context.get("validator_type"),
                excluded_columns,
                scan_rows,
            )

            # SCRUM-7: Assign table_id for hyperlinks/tracking
            if table_id:
                result.table_id = table_id
            else:
                logging.warning(
                    f"Missing table_id for table index {idx}, heading: {heading}"
                )
                result.context["hyperlink_missing"] = True

            # O1: Per-table observability logging (normalization + validator pipeline).
            # Phase 5.4: run_id and per-table context (extractor_engine, quality_score, failure_reason_code).
            norm_meta = result.context.get("normalization_metadata", {}) or {}
            total_meta = result.context.get("total_row_metadata", {}) or {}
            run_id = getattr(self.telemetry.run_telemetry, "run_id", "") or ""
            observability_payload = {
                "run_id": run_id,
                "table_id": result.table_id,
                "table_index": idx,
                "validation_status": validation_status,
                "heading": heading or f"Table {idx + 1}",
                "validator_type": result.context.get("validator_type"),
                "extractor_engine": result.context.get("extractor_engine"),
                "quality_score": result.context.get("quality_score"),
                "failure_reason_code": result.context.get("failure_reason_code"),
                "code_columns": (
                    result.context.get("excluded_columns")
                    or result.context.get("code_columns")
                    or []
                ),
                "amount_columns": result.context.get("amount_columns") or [],
                "is_movement_table": result.context.get("is_movement_table"),
                "total_row_idx": total_meta.get("total_row_idx"),
                "total_row_method": total_meta.get("method"),
                "dedup_period_columns_applied": norm_meta.get(
                    "dedup_period_columns_applied"
                ),
                "duplicated_period_groups_count": len(
                    norm_meta.get("duplicated_period_groups", [])
                ),
                "dedup_conflicts_count": len(norm_meta.get("dedup_conflicts", [])),
                "suspicious_wide_table": norm_meta.get("suspicious_wide_table"),
                "misalignment_suspected": norm_meta.get("misalignment_suspected"),
                # P0: NOTE structure observability and WARN reason_code
                "label_col": result.context.get("label_col"),
                "amount_cols": result.context.get("amount_cols"),
                "segments_count": result.context.get("segments_count"),
                "structure_confidence": result.context.get("structure_confidence"),
                "row_type_counts": result.context.get("row_type_counts"),
                "reason_code": (
                    result.context.get("reason_code")
                    if (result.status_enum or "") == "WARN"
                    else None
                ),
            }
            logger.info("Table observability: %s", observability_payload)

            result_dict = result.to_dict()
            # Expose table_type at the top-level for plan/golden tests.
            result_dict["table_type"] = result_dict.get("table_type") or (
                (result_dict.get("context") or {}).get("classifier_primary_type")
            )
            results.append(result_dict)

            # E2: End tracking this table and record metrics
            validator_type = result_dict.get("context", {}).get("validator_type")
            self.telemetry.end_table(table, heading, validator_type, result_dict)

        return results

    def _build_cf_registry(
        self, tables: List[Tuple[pd.DataFrame, Optional[str], Dict]]
    ) -> Dict[str, tuple[float, float]]:
        """
        Build a document-level registry for Cash Flow codes: code -> (CY, PY).

        Input tuples are (df, heading, table_context). The registry is run-scoped and
        must be safe to recompute deterministically from table content.
        """
        from ..utils.numeric_utils import parse_numeric
        from ..utils.table_normalizer import TableNormalizer

        registry: Dict[str, tuple[float, float]] = {}
        code_re = re.compile(r"^[0-9]{1,4}[A-Z]?$")

        for df, _heading, _ctx in tables:
            if df is None or df.empty:
                continue

            code_col = next(
                (c for c in df.columns if str(c).strip().lower() == "code"), None
            )
            if not code_col:
                code_col = TableNormalizer._detect_code_column_with_synonyms(df)
            if not code_col:
                continue

            cy_col = next(
                (c for c in df.columns if str(c).strip().upper() == "CY"), None
            )
            py_col = next(
                (c for c in df.columns if str(c).strip().upper() == "PY"), None
            )
            if not (cy_col and py_col):
                # Minimal fallback: attempt to pick numeric columns excluding code-like columns.
                candidate_cols = [c for c in df.columns if c != code_col]
                if len(candidate_cols) >= 2:
                    from ..utils.column_detector import ColumnDetector

                    cy_col, py_col = ColumnDetector.detect_financial_columns_advanced(
                        df[candidate_cols]
                    )
            if not (cy_col and py_col):
                continue

            for _, row in df.iterrows():
                raw = str(row.get(code_col, "")).strip()
                code = re.sub(r"\s+", "", raw)
                if not code or not code_re.match(code):
                    continue
                cy = float(parse_numeric(row.get(cy_col, "")) or 0.0)
                py = float(parse_numeric(row.get(py_col, "")) or 0.0)
                prev_cy, prev_py = registry.get(code, (0.0, 0.0))
                registry[code] = (prev_cy + cy, prev_py + py)

        return registry

    def _validate_single_table(
        self,
        table: pd.DataFrame,
        heading: Optional[str],
        table_context: Optional[Dict] = None,
    ) -> "ValidationResult":
        """
        Validate a single table using appropriate validator.
        """
        import traceback

        from ..core.validators.base_validator import ValidationResult

        # Legacy compatibility path: allow routing through legacy_engine for baseline-authoritative
        # flows while stripping non-baseline routing hints from table_context.
        try:
            flags = get_feature_flags()
            if bool(flags.get("baseline_authoritative_default", False)) and bool(
                flags.get("legacy_bug_compatibility_mode", False)
            ):
                ctx = dict(table_context or {})
                # Remove non-baseline routing hints; keep statement_group_id for grouping continuity.
                for k in [
                    "statement_family",
                    "routing_reason",
                    "continuation_confidence",
                    "continuation_evidence",
                ]:
                    ctx.pop(k, None)
                legacy_result = self.legacy_engine.validate_table(
                    table, heading, table_context=ctx
                )
                if isinstance(legacy_result, ValidationResult):
                    if "validator_type" not in legacy_result.context:
                        legacy_result.context["validator_type"] = "LegacyEngine"
                    return legacy_result
        except Exception:
            # Fall through to canonical validator path (legacy_engine is best-effort).
            pass

        # Get appropriate validator
        try:
            validator, skip_reason = ValidatorFactory.get_validator(
                table, heading, context=self.context, table_context=table_context
            )
            if validator is None:
                # Determine rule_id and status message based on skip_reason
                if skip_reason == "SKIPPED_NO_NUMERIC_EVIDENCE":
                    # Parity contract: "no numeric dispatch" is INFO with rule_id NO_NUMERIC_EVIDENCE
                    # (not a SKIPPED_* marker).
                    flags = get_feature_flags()
                    rule_id = (
                        "NO_NUMERIC_EVIDENCE"
                        if bool(flags.get("legacy_parity_mode"))
                        else "SKIPPED_NO_NUMERIC_EVIDENCE"
                    )
                    status_msg = "INFO: Table bị skip (không đủ bằng chứng số)"
                    reason_desc = "BalanceSheet table skipped due to insufficient numeric evidence"
                else:
                    # Spine 3: Re-run 2-phase classifier; do not label as footer if classifier says do not skip
                    heading_lower = (heading or "").strip().lower()
                    should_skip, _evidence = classify_footer_signature(
                        table, heading=heading_lower
                    )
                    if not should_skip:
                        rule_id = "SKIPPED_NO_NUMERIC_EVIDENCE"
                        status_msg = "INFO: Table bị skip (không đủ bằng chứng số)"
                        reason_desc = "Table skipped (classifier: not footer/signature, insufficient numeric evidence)"
                    else:
                        rule_id = "SKIPPED_FOOTER_SIGNATURE"
                        status_msg = "INFO: Table bị skip (footer/chữ ký)"
                        reason_desc = "Detected as footer/signature table"

                return ValidationResult(
                    status=status_msg,
                    marks=[],
                    cross_ref_marks=[],
                    rule_id=rule_id,
                    status_enum="INFO",
                    context={
                        "heading": heading,
                        "table_shape": table.shape if not table.empty else (0, 0),
                        "reason": reason_desc,
                    },
                )
            validator_type = type(validator).__name__
        except Exception as e:
            return ValidationResult(
                status=f"ERROR: Failed to create validator: {str(e)}",
                marks=[],
                cross_ref_marks=[],
                rule_id="VALIDATOR_FACTORY_ERROR",
                status_enum="ERROR",
                context={
                    "heading": heading,
                    "table_shape": table.shape if not table.empty else (0, 0),
                },
                exception_type=type(e).__name__,
                exception_message=str(e),
            )

        # Validate table with fail-safe wrapper
        try:
            # Observability: inject heading into df.attrs for validators, then restore.
            _orig_attrs = dict(getattr(table, "attrs", {}) or {})
            try:
                table.attrs["heading"] = heading
                result = validator.validate(table, heading, table_context=table_context)
            finally:
                try:
                    table.attrs.clear()
                    table.attrs.update(_orig_attrs)
                except Exception:
                    pass
            if not result.rule_id or result.rule_id == "UNKNOWN":
                result.rule_id = f"{validator_type}_VALIDATION"
            if "validator_type" not in result.context:
                result.context["validator_type"] = validator_type

            # Calculate Severity/Confidence
            if result.status_enum in ["FAIL", "ERROR", "WARN"] and hasattr(
                validator, "_calculate_severity"
            ):
                try:
                    is_skipped = (
                        "skip" in result.status.lower() or "INFO" in result.status_enum
                    )
                    max_diff = 0.0
                    for mark in result.marks:
                        diff_val = mark.get("diff", 0)
                        if diff_val is not None:
                            try:
                                diff_abs = abs(float(diff_val))
                                if diff_abs > max_diff:
                                    max_diff = diff_abs
                            except (ValueError, TypeError):
                                pass

                    result.severity = validator._calculate_severity(
                        result.rule_id, max_diff, is_skipped
                    )
                    result.confidence = validator._calculate_confidence(
                        result.rule_id, is_skipped, False, result.context
                    )
                except Exception:
                    pass
            return result
        except Exception as e:
            return ValidationResult(
                status=f"ERROR: Unexpected error during validation - {str(e)}",
                marks=[],
                cross_ref_marks=[],
                rule_id="VALIDATION_UNEXPECTED_ERROR",
                status_enum="ERROR",
                context={
                    "heading": heading,
                    "table_shape": table.shape if not table.empty else (0, 0),
                    "validator_type": validator_type,
                    "traceback": traceback.format_exc(),
                },
                exception_type=type(e).__name__,
                exception_message=str(e),
            )

    def _is_table_without_total(self, table: pd.DataFrame, heading_lower: str) -> bool:
        """Check if table should be skipped from total validation."""
        if heading_lower in TABLES_WITHOUT_TOTAL:
            return True
        subset = table.iloc[2:]
        numeric_content = subset.map(
            lambda x: pd.to_numeric(
                str(x).replace(",", "").replace("(", "-").replace(")", ""),
                errors="coerce",
            )
        )
        return bool(numeric_content.isna().all().all())

    def _generate_report(
        self,
        table_heading_pairs: List[Tuple[pd.DataFrame, Optional[str]]],
        results: List[Dict],
        excel_path: str,
        telemetry: Optional[TelemetryCollector] = None,
    ) -> None:
        """Generate Excel report."""
        flags = get_feature_flags()
        exclude_footer = flags.get("metrics_exclude_footer_signature_artifacts", True)

        if exclude_footer:
            exclude_indices = {
                i
                for i, r in enumerate(results)
                if r.get("rule_id") == "SKIPPED_FOOTER_SIGNATURE"
            }
            results_for_output = [
                r for i, r in enumerate(results) if i not in exclude_indices
            ]
            table_heading_pairs_for_output = [
                (t, h)
                for i, (t, h) in enumerate(table_heading_pairs)
                if i not in exclude_indices
            ]
            excluded_count = len(exclude_indices)
            for i in exclude_indices:
                table_id = results[i].get("context", {}).get("table_id") or (
                    results[i].get("table_id")
                )
                if not table_id and i < len(table_heading_pairs):
                    h = table_heading_pairs[i][1] if table_heading_pairs[i][1] else ""
                    table_id = f"tbl_{i + 1:03d}_{(h or 'unknown')[:30]}"
                logger.info(
                    "Table excluded from output: footer/signature artifact (table_id=%s)",
                    table_id or f"index_{i}",
                )
            if excluded_count:
                logger.info(
                    "Excluded %d footer/signature artifacts from output",
                    excluded_count,
                )
        else:
            results_for_output = results
            table_heading_pairs_for_output = table_heading_pairs
            excluded_count = 0

        wb = self.excel_writer.create_workbook()
        sheet_positions = self.excel_writer.write_tables_consolidated(
            wb, table_heading_pairs_for_output, results_for_output
        )
        # P3-U1: Sort results by severity for Summary/Focus List (ERROR > FAIL_TOOL_* > FAIL_DATA > FAIL > WARN > INFO > PASS)
        severity_map = {
            "ERROR": 0,
            "FAIL_TOOL_EXTRACT": 1,
            "FAIL_TOOL_LOGIC": 2,
            "FAIL_DATA": 3,
            "FAIL": 4,
            "WARN": 5,
            "INFO": 6,
            "PASS": 7,
        }
        sorted_results = sorted(
            results_for_output,
            key=lambda x: (
                severity_map.get(str(x.get("status_enum") or "FAIL"), 4),
                x.get("table_index", 0),
            ),
        )

        self.excel_writer.write_executive_summary(wb, sorted_results)
        self.excel_writer.write_focus_list(wb, sorted_results, telemetry=telemetry)
        self.excel_writer.write_summary_sheet(
            wb, results_for_output, sheet_positions, telemetry=telemetry
        )
        if telemetry:
            self.excel_writer.write_telemetry_sheet(
                wb, telemetry, skipped_footer_signature_count=excluded_count
            )
        self.excel_writer.write_contract_v2_sheets(
            wb, results_for_output, telemetry=telemetry
        )
        if "Sheet" in wb.sheetnames:
            del wb["Sheet"]
        self.excel_writer.save_workbook(wb, excel_path)
        # self.file_handler.open_file_safely(excel_path)  # Moved to UI layer control

    async def process_document_async(
        self, word_path: str, excel_path: str
    ) -> Dict[str, Any]:
        """
        Async shell entrypoint for canonical runtime.

        Production correctness is intentionally delegated to the same single-path
        legacy canonical flow used by audit_document().
        """
        return await asyncio.to_thread(self.audit_document, word_path, excel_path)
