"""
Main audit service orchestrating the entire validation workflow.
"""

import logging
import re
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

import pandas as pd

from ..config.constants import TABLES_WITHOUT_TOTAL
from ..config.feature_flags import get_feature_flags
from ..core.cache_manager import AuditContext, LRUCacheManager, cross_check_marks
from ..core.exceptions import FileProcessingError, SecurityError, ValidationError
from ..core.validators.base_validator import ValidationResult
from ..core.validators.cash_flow_validator import CashFlowValidator
from ..core.validators.factory import ValidatorFactory
from ..io import ExcelWriter, FileHandler
from ..io.word_reader import AsyncWordReader, WordReader
from ..utils.column_detector import ColumnDetector
from ..utils.numeric_utils import parse_numeric
from ..utils.skip_classifier import classify_footer_signature
from ..utils.table_normalizer import TableNormalizer
from ..utils.telemetry_collector import TelemetryCollector
from .base_service import BaseService

logger = logging.getLogger(__name__)


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

        # Keep cache_manager for backward compatibility (deprecated)
        self.cache_manager = self.context.cache

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
            # Clear marks and set filename at start of audit run
            self.context.clear()
            self.context.current_filename = str(Path(word_path).absolute())

            # Also clear global marks for backward compatibility
            # Note: This is still shared, but task-local ContextVar based fixation
            # in AuditContext is the primary future-proof fix.
            cross_check_marks.clear()

            # Validate inputs with proper error handling
            if not self.file_handler.validate_path(word_path):
                raise SecurityError(f"Invalid or unsafe Word file path: {word_path}")

            # SEC-1: Check for zip bomb
            if not self.file_handler.validate_docx_safety(word_path):
                raise SecurityError(
                    f"Potential Zip Bomb detected or invalid DOCX structure: {word_path}"
                )

            # Read tables from Word document
            # Each item is now (df, heading, table_context)
            all_tables_with_context = self.word_reader.read_tables_with_headings(
                word_path
            )

            if not all_tables_with_context:
                raise ValueError("No tables found in Word document")

            # SCRUM-6: Start telemetry collection
            self.telemetry.start_run()

            # Validate all tables
            results = self._validate_tables(all_tables_with_context)

            # SCRUM-6: End telemetry collection
            self.telemetry.end_run()

            # Generate Excel report (with telemetry)
            # excel_writer expects (df, heading) pairs, so extract that.
            table_heading_pairs_for_report = [
                (item[0], item[1]) for item in all_tables_with_context
            ]
            self._generate_report(
                table_heading_pairs_for_report, results, excel_path, self.telemetry
            )

            return {
                "success": True,
                "tables_processed": len(all_tables_with_context),
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
            # Wrap unknown exceptions
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

        E2: Includes telemetry tracking for each table validation.

        Args:
            table_heading_pairs: List of (table_df, heading) tuples

        Returns:
            List of validation results
        """
        results: List[Dict] = []
        flags = get_feature_flags()
        use_cf_cross = flags.get("cashflow_cross_table_context", False)
        use_big4_engine = flags.get("enable_big4_engine", False)
        use_big4_shadow = flags.get("enable_big4_shadow", True)

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

        if use_big4_engine:
            return self._validate_tables_big4(normalized_pairs)

        # Pass 1: identify cash flow tables (by classifier) when cross-table context is enabled
        cf_indices: set[int] = set()
        cf_tables: List[Tuple[pd.DataFrame, Optional[str], Dict]] = []

        if use_cf_cross:
            for idx, (table, heading, table_context) in enumerate(normalized_pairs):
                try:
                    validator, skip_reason = ValidatorFactory.get_validator(
                        table,
                        heading,
                        context=self.context,
                        table_context=table_context,
                    )
                except Exception:
                    continue

                if validator is not None and isinstance(validator, CashFlowValidator):
                    cf_indices.add(idx)
                    cf_tables.append((table, heading, table_context))

        # Build full cash flow registry before any CF validation (P2-1)
        orig_registry = None
        if use_cf_cross and cf_tables:
            full_registry = self._build_cf_registry(cf_tables)
            logger.info(
                "Cash flow cross-table context enabled: cf_tables_count=%s, registry_codes=%s",
                len(cf_tables),
                len(full_registry),
            )
            orig_registry = self.context.cash_flow_registry
            self.context.cash_flow_registry = full_registry

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

            # Merge classification context + table context into result.context for observability
            classification_ctx = self.context.get_last_classification_context() or {}
            heading_source = (table_context or {}).get("heading_source")
            excluded_columns = result.context.get("excluded_columns", [])
            scan_rows = classification_ctx.get("scan_rows")

            enriched_ctx = {
                "heading": heading or f"Table {idx + 1}",
                "table_index": idx,
                "heading_source": heading_source,
                "heading_confidence": (table_context or {}).get("heading_confidence"),
                "classifier_primary_type": classification_ctx.get(
                    "classifier_primary_type"
                ),
                "classifier_confidence": classification_ctx.get(
                    "classifier_confidence"
                ),
                "classifier_reason": classification_ctx.get("classifier_reason"),
                "scan_rows": scan_rows,
                "validator_type": result.context.get("validator_type"),
                "excluded_columns": excluded_columns,
                "table_shape": table.shape if not table.empty else (0, 0),
            }

            # Mark when cross-table CF registry was used
            if use_cf_cross and idx in cf_indices:
                enriched_ctx["cross_table_used"] = True

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
            }
            logger.info("Table observability: %s", observability_payload)

            result_dict = result.to_dict()
            results.append(result_dict)

            # E2: End tracking this table and record metrics
            validator_type = result_dict.get("context", {}).get("validator_type")
            self.telemetry.end_table(table, heading, validator_type, result_dict)

        # Restore original registry after CF validation
        if orig_registry is not None:
            self.context.cash_flow_registry = orig_registry

        if use_big4_shadow and not use_big4_engine:
            try:
                big4_results = self._validate_tables_big4(normalized_pairs)
                self._compare_shadow_results(results, big4_results)
            except Exception as e:
                logger.error("Big4 shadow engine failed: %s", str(e), exc_info=True)

        return results

    def _compare_shadow_results(
        self, legacy_results: List[Dict], big4_results: List[Dict]
    ) -> None:
        """Compare legacy and Big4 results for A/B testing."""
        if len(legacy_results) != len(big4_results):
            logger.warning(
                "Shadow mode mismatch: Legacy produced %d results, Big4 produced %d results",
                len(legacy_results),
                len(big4_results),
            )
            return

        divergences = 0
        for i, (leg, big4) in enumerate(zip(legacy_results, big4_results)):
            leg_valid = leg.get("is_valid")
            big4_valid = big4.get("is_valid")

            if leg_valid != big4_valid:
                divergences += 1
                logger.info(
                    "Shadow mode divergence at index %d: Legacy is_valid=%s, Big4 is_valid=%s. "
                    "Legacy errors: %s, Big4 errors: %s",
                    i,
                    leg_valid,
                    big4_valid,
                    leg.get("errors", []),
                    big4.get("errors", []),
                )
        if divergences == 0:
            logger.info(
                "Shadow mode comparison: All %d results match in valid status.",
                len(legacy_results),
            )
        else:
            logger.info(
                "Shadow mode comparison: %d/%d divergences in valid status.",
                divergences,
                len(legacy_results),
            )

    def _validate_tables_big4(
        self, normalized_pairs: List[Tuple[pd.DataFrame, Optional[str], Dict]]
    ) -> List[Dict]:
        """Validate tables using the new Big4 Engine."""
        from collections import defaultdict

        from ..core.classification.table_classifier_v2 import TableClassifierV2
        from ..core.evidence.severity import Severity
        from ..core.materiality.materiality_engine import MaterialityEngine
        from ..core.model.financial_model import FinancialModel
        from ..core.model.fs_anchor_index import (
            build_fs_anchor_index,
            infer_note_ref_for_table,
            infer_unit_hint_for_table,
        )
        from ..core.rules.rule_registry import default_registry
        from ..core.scoring.scoring_engine import ScoringEngine
        from ..core.validators.audit_grade_validator import AuditGradeValidator
        from ..core.validators.base_validator import ValidationResult
        from ..utils.column_detector import ColumnDetector
        from ..utils.table_normalizer import TableNormalizer

        registry = default_registry
        materiality = MaterialityEngine()
        auditor = AuditGradeValidator(registry, materiality)
        scorer = ScoringEngine()
        classifier = TableClassifierV2()

        model = FinancialModel()
        results: List[Dict] = []
        tables_info = []

        # 1. Classify and build the document-level FinancialModel
        import time as _time

        for idx, (table, heading, table_context) in enumerate(normalized_pairs):
            _t_start = _time.time()  # record per-table start before classification

            # Extract heading safely from table metadata if not provided by tuple
            table_heading = heading
            if not table_heading:
                table_heading = getattr(table, "heading", "")

            classification = classifier.classify(table=table, heading=table_heading)
            table_type_str = (
                classification.table_type.value.upper()
                if hasattr(classification, "table_type")
                else str(classification).upper()
            )

            code_col = TableNormalizer._detect_code_column_with_synonyms(table)
            cur_col, prior_col = ColumnDetector.detect_financial_columns_advanced(table)
            amount_cols = []
            if cur_col:
                amount_cols.append(cur_col)
            if prior_col:
                amount_cols.append(prior_col)

            safe_heading = re.sub(r"[^A-Za-z0-9]", "_", heading or "unknown")
            slug = safe_heading[:50].strip("_") or "unnamed"
            table_id = f"tbl_{idx + 1:03d}_{slug}"
            table_id = re.sub(r"[^A-Za-z0-9_]", "_", table_id)

            t_info = {
                "table_id": table_id,
                "table_type": table_type_str,
                "classification": classification,
                "df": table,
                "code_col": code_col,
                "amount_cols": amount_cols,
                "original_index": idx,
                "heading": heading,
                "context": table_context or {},
            }
            t_info["context"].update(
                {
                    "table_index": idx,
                    "table_type": table_type_str,
                    "heading": heading,
                    "total_row_metadata": (table_context or {}).get(
                        "total_row_metadata"
                    )
                    or {},
                }
            )
            logger.info(
                "[Big4] Classified tbl_%03d heading=%r → type=%s conf=%.2f code_col=%s amount_cols=%s",
                idx + 1,
                heading,
                table_type_str,
                getattr(classification, "confidence", 0.0),
                code_col,
                amount_cols,
            )
            t_info["_telemetry_start"] = _t_start  # stash for loop 2
            tables_info.append(t_info)
            model.add_table(t_info)

        for t_info in tables_info:
            t_info.setdefault("context", {})["unit_hint"] = infer_unit_hint_for_table(
                t_info
            )
        model.fs_anchor_index = build_fs_anchor_index(tables_info)
        for t_info in tables_info:
            if t_info.get("table_type") in ("GENERIC_NOTE", "TAX_NOTE"):
                t_info["inferred_note_ref"] = infer_note_ref_for_table(
                    t_info, model.fs_anchor_index
                )
            else:
                t_info["inferred_note_ref"] = ""

        for t_info in tables_info:
            if t_info.get("table_type") in ("GENERIC_NOTE", "TAX_NOTE") and t_info.get(
                "amount_cols"
            ):
                df_t = t_info["df"]
                n = len(df_t)
                if n >= 2:
                    t_info["total_row_idx"] = n - 1
                    t_info["detail_rows"] = list(range(0, n - 1))
                else:
                    t_info["total_row_idx"] = None
                    t_info["detail_rows"] = []

        # 2. Execute orchestration engine
        all_evidence = auditor.validate_model(model)

        # 3. Calculate global document score
        model_score = scorer.evaluate_score(all_evidence)
        logger.info("[Big4 Engine] Completed with model score %.2f/100", model_score)

        # 4. Map the evidence back to legacy ValidationResult dicts
        evidence_by_table = defaultdict(list)
        cross_table_evidence = []

        for ev in all_evidence:
            if "source_locations" in ev.metadata and ev.metadata["source_locations"]:
                involved_tables = {
                    loc["table_id"]
                    for loc in ev.metadata["source_locations"]
                    if "table_id" in loc
                }
                for t_id in involved_tables:
                    evidence_by_table[t_id].append(ev)
            elif ev.table_id:
                evidence_by_table[ev.table_id].append(ev)
            else:
                cross_table_evidence.append(ev)

        for t_info in tables_info:
            table_id = t_info["table_id"]
            idx = t_info["original_index"]
            my_evidence = evidence_by_table[table_id]

            failed_ev = [e for e in my_evidence if e.is_material]
            if failed_ev:
                max_sev = max(failed_ev, key=lambda x: x.severity.value)
                status_enum = "FAIL"
                if max_sev.severity == Severity.CRITICAL:
                    status_enum = "ERROR"

                issues = []
                for e in failed_ev:
                    calc = getattr(e, "actual", 0) or 0
                    repo = getattr(e, "expected", 0) or 0
                    diff = getattr(e, "diff", 0) or 0
                    issue_str = (
                        f"{e.assertion_text} - Tính={calc:,.0f}, Thực tế={repo:,.0f}, Lệch={diff:,.0f}"
                        if (calc or repo or diff)
                        else e.assertion_text
                    )
                    issues.append(issue_str)

                preview = "; ".join(issues[:10])
                more = f" ... (+{len(issues) - 10} vấn đề)" if len(issues) > 10 else ""
                status_str = f"{status_enum}: Big4 Engine - {len(failed_ev)} sai lệch. {preview}{more}"
            elif not my_evidence:
                # Chỉ đánh dấu "không có assertions" cho bảng FS có quy tắc Big4
                fs_types = (
                    "FS_BALANCE_SHEET",
                    "FS_INCOME_STATEMENT",
                    "FS_CASH_FLOW",
                    "FS_EQUITY",
                )
                note_types = ("GENERIC_NOTE", "TAX_NOTE")
                if t_info["table_type"] in fs_types:
                    status_enum = "INFO_SKIPPED"
                    status_str = "INFO: Bảng không có assertions cụ thể (đã được gộp hoặc không có quy tắc)."
                elif t_info["table_type"] in note_types:
                    status_enum = "INFO_SKIPPED"
                    amount_cols = t_info.get("amount_cols") or []
                    if amount_cols:
                        status_str = (
                            "INFO: Bảng ghi chú số - chưa áp dụng quy tắc NOTE_SUM_TO_TOTAL / tie-out."
                        )
                    else:
                        status_str = (
                            "INFO: Bảng ghi chú (narrative - không kiểm tra số)."
                        )
                else:
                    status_enum = "INFO_SKIPPED"
                    status_str = (
                        "INFO: Bảng chưa phân loại hoặc không có assertions cụ thể."
                    )
            else:
                status_enum = "PASS"
                status_str = f"PASS: Big4 Engine - kiểm tra {len(my_evidence)} assertions KHỚP (0 sai lệch)"

            import contextlib

            marks = []
            for ev in my_evidence:
                col_name = ev.source_cols[0] if ev.source_cols else None
                col_idx = None
                if col_name is not None:
                    with contextlib.suppress(ValueError):
                        col_idx = list(t_info["df"].columns).index(col_name)

                if (
                    "source_locations" in ev.metadata
                    and ev.metadata["source_locations"]
                ):
                    ev_rows = {
                        loc["row_idx"]
                        for loc in ev.metadata["source_locations"]
                        if loc.get("table_id") == table_id
                    }
                else:
                    # Collect all rows involved in this evidence (components + target)
                    ev_rows = getattr(ev, "source_rows", []) or []

                if not ev_rows:
                    # Fallback if no source_rows specified
                    marks.append(
                        {
                            "row": None,
                            "col": col_idx,
                            "diff": ev.diff,
                            "msg": ev.assertion_text,
                            "ok": not ev.is_material,
                            "severity": ev.severity.name,
                        }
                    )
                else:
                    for r in ev_rows:
                        marks.append(
                            {
                                "row": r,
                                "col": col_idx,
                                "diff": ev.diff,
                                "msg": ev.assertion_text,
                                "ok": not ev.is_material,
                                "severity": ev.severity.name,
                            }
                        )

            # Extract classifier metadata from the classification result
            classification = t_info.get("classification")
            classifier_type = t_info["table_type"]  # already .upper()'\'d
            classifier_conf = getattr(classification, "confidence", None)
            classifier_reason = getattr(classification, "reason", None)

            # Extract heading metadata from table_context
            orig_ctx = t_info.get("context") or {}
            heading_source = orig_ctx.get("heading_source")
            heading_confidence = orig_ctx.get("heading_confidence")

            assertions_count = len(my_evidence)

            res = ValidationResult(
                status=status_str,
                marks=marks,
                rule_id=f"BIG4_{t_info['table_type']}",
                status_enum=status_enum,
                context={
                    "validator_type": "Big4Engine",
                    "table_id": table_id,
                    "heading": t_info["heading"],
                    "big4_model_score": model_score,
                    # Telemetry fields — read by TelemetryCollector.end_table()
                    "classifier_primary_type": classifier_type,
                    "classifier_confidence": classifier_conf,
                    "classifier_reason": classifier_reason,
                    "heading_source": heading_source,
                    "heading_confidence": heading_confidence,
                    "assertions_count": assertions_count,
                },
                table_id=table_id,
            )

            res.context.update(orig_ctx)
            # Re-apply Big4-specific keys so orig_ctx.update() doesn't clobber them
            res.context["classifier_primary_type"] = classifier_type
            res.context["classifier_confidence"] = classifier_conf
            res.context["classifier_reason"] = classifier_reason
            res.context["heading_source"] = heading_source
            res.context["heading_confidence"] = heading_confidence
            res.context["assertions_count"] = assertions_count

            res_dict = res.to_dict()
            # assertions_count must be top-level for TelemetryCollector.end_table()
            res_dict["assertions_count"] = assertions_count
            results.append(res_dict)

            # FIX: restore per-table start time so end_table() doesn't skip tables.
            # The start/end loop is split (classify in loop-1, result-map in loop-2),
            # so _current_table_start=None after the first end_table call silently
            # drops all subsequent tables from telemetry (Table Count stays at 1).
            self.telemetry._current_table_start = t_info.get("_telemetry_start")
            self.telemetry._current_table_index = len(
                self.telemetry.run_telemetry.tables
            )
            self.telemetry.end_table(
                t_info["df"], t_info["heading"], "Big4Engine", res_dict
            )

        return results

    def _build_cf_registry(
        self, cf_tables: List[Tuple[pd.DataFrame, Optional[str], Dict]]
    ) -> Dict[str, Tuple[float, float]]:
        """
        Build document-level cash-flow registry: code -> (current_year, prior_year)
        from all Cash Flow tables before any CF validation (P2-1).
        """
        registry: Dict[str, Tuple[float, float]] = {}

        for table, _heading, _ in cf_tables:
            df = table
            if df.empty or len(df.columns) < 2:
                continue

            # Detect Code column
            code_col = TableNormalizer._detect_code_column_with_synonyms(df)
            if not code_col:
                code_col = next(
                    (c for c in df.columns if str(c).strip().lower() == "code"), None
                )
            if not code_col:
                continue

            # Detect current/prior year columns
            cur_col, prior_col = ColumnDetector.detect_financial_columns_advanced(df)
            if cur_col is None or prior_col is None:
                if len(df.columns) >= 2:
                    cur_col, prior_col = df.columns[-2], df.columns[-1]
                else:
                    continue

            for _, row in df.iterrows():
                raw_code = row.get(code_col, "")
                code = str(raw_code).strip()
                if not code:
                    continue

                norm_code = re.sub(r"\s+", "", code)
                if not re.match(r"^[0-9]+[A-Z]?$", norm_code):
                    continue

                cur_val = parse_numeric(row.get(cur_col, ""))
                pr_val = parse_numeric(row.get(prior_col, ""))
                agg_cur, agg_pr = registry.get(norm_code, (0.0, 0.0))
                registry[norm_code] = (agg_cur + cur_val, agg_pr + pr_val)

        return registry

    def _validate_single_table(
        self,
        table: pd.DataFrame,
        heading: Optional[str],
        table_context: Optional[Dict] = None,
    ) -> ValidationResult:
        """
        Validate a single table using appropriate validator.
        """
        import traceback

        from ..core.validators.base_validator import ValidationResult
        from ..core.validators.factory import ValidatorFactory

        # Get appropriate validator
        try:
            validator, skip_reason = ValidatorFactory.get_validator(
                table, heading, context=self.context, table_context=table_context
            )
            if validator is None:
                # Don't skip equity ownership tables even if low numeric evidence (% columns)
                heading_lower = (heading or "").strip().lower()
                is_equity_ownership = any(
                    kw in heading_lower
                    for kw in [
                        "equity owned",
                        "voting rights",
                        "cơ cấu sở hữu",
                        "ownership structure",
                        "shareholding",
                    ]
                )
                if is_equity_ownership and skip_reason == "SKIPPED_NO_NUMERIC_EVIDENCE":
                    from ..core.validators.generic_validator import (
                        GenericTableValidator,
                    )

                    validator = GenericTableValidator(context=self.context)
                    skip_reason = None

                # Ticket-5: Escape hatch for confidently classified primary statements
                # When numeric evidence is low but classifier is confident, force validation
                if validator is None and skip_reason == "SKIPPED_NO_NUMERIC_EVIDENCE":
                    classification_ctx = (
                        self.context.get_last_classification_context() or {}
                    )
                    classifier_type = classification_ctx.get(
                        "classifier_primary_type", ""
                    )
                    classifier_conf = classification_ctx.get(
                        "classifier_confidence", 0.0
                    )
                    primary_types = {
                        "FS_BALANCE_SHEET",
                        "FS_INCOME_STATEMENT",
                        "FS_CASH_FLOW",
                    }
                    if (
                        classifier_type in primary_types
                        and (classifier_conf or 0) >= 0.6
                    ):
                        logger.warning(
                            "Ticket-5 escape hatch: forcing validation for %s (confidence=%.2f, numeric_evidence low)",
                            classifier_type,
                            classifier_conf or 0,
                        )
                        from ..core.validators.generic_validator import (
                            GenericTableValidator,
                        )

                        validator = GenericTableValidator(context=self.context)
                        skip_reason = None
            if validator is None:
                # Determine rule_id and status message based on skip_reason
                if skip_reason == "SKIPPED_NO_NUMERIC_EVIDENCE":
                    rule_id = "SKIPPED_NO_NUMERIC_EVIDENCE"
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
            result = validator.validate(table, heading, table_context=table_context)
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
        if "Sheet" in wb.sheetnames:
            del wb["Sheet"]
        self.excel_writer.save_workbook(wb, excel_path)
        # self.file_handler.open_file_safely(excel_path)  # Moved to UI layer control

    async def process_document_async(
        self, word_path: str, excel_path: str
    ) -> Dict[str, Any]:
        """Async audit workflow."""
        try:
            # Clear marks and set filename at start
            self.context.clear()
            self.context.current_filename = str(Path(word_path).absolute())
            cross_check_marks.clear()

            if not self.file_handler.validate_path(word_path):
                raise SecurityError(f"Invalid or unsafe Word file path: {word_path}")

            if not self.file_handler.validate_docx_safety(word_path):
                raise SecurityError(f"Potential Zip Bomb detected: {word_path}")

            async_reader = self.async_word_reader or AsyncWordReader(max_workers=4)
            async with async_reader:
                table_heading_pairs = await async_reader.read_document_async(word_path)

            if not table_heading_pairs:
                raise ValueError("No tables found in Word document")

            self.telemetry.start_run()
            results = self._validate_tables(table_heading_pairs)
            self.telemetry.end_run()

            # excel_writer expects (df, heading) pairs; strip table_context
            table_heading_pairs_for_report = [
                (df, heading) for df, heading, _ in table_heading_pairs
            ]
            self._generate_report(
                table_heading_pairs_for_report, results, excel_path, self.telemetry
            )

            return {
                "success": True,
                "tables_processed": len(table_heading_pairs),
                "results": results,
                "output_path": excel_path,
            }

        except (SecurityError, FileProcessingError, ValidationError) as e:
            return {
                "success": False,
                "error": str(e),
                "error_type": type(e).__name__,
                "tables_processed": 0,
                "results": [],
            }
        except Exception as e:
            import traceback

            traceback.print_exc()
            return {
                "success": False,
                "error": f"Unexpected error: {str(e)}",
                "error_type": "QualityAuditError",
                "tables_processed": 0,
                "results": [],
            }
