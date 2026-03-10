"""
Cash Flow validator implementation.
"""

import logging
import re
from typing import Dict, List, Optional, Tuple

import pandas as pd

from ...config.feature_flags import get_feature_flags
from ...utils.column_detector import ColumnDetector
from ...utils.numeric_utils import parse_numeric
from ..cache_manager import AuditContext
from .base_validator import BaseValidator, ValidationResult

logger = logging.getLogger(__name__)


class CashFlowValidator(BaseValidator):
    """Validator for cash flow statement."""

    def validate(
        self,
        df: pd.DataFrame,
        heading: Optional[str] = None,
        table_context: Optional[Dict] = None,
    ) -> ValidationResult:
        """
        Validate cash flow statement table.

        Args:
            df: DataFrame containing cash flow data
            heading: Table heading (unused)
            table_context: Optional table metadata (extraction quality, etc.)

        Returns:
            ValidationResult: Validation results
        """
        early = self._check_extraction_quality(table_context)
        if early is not None:
            return early

        self._current_table_context = {
            "table_id": (table_context or {}).get("table_id", ""),
            "heading": heading or "",
        }
        try:
            # P2-T1: Use centralized TableNormalizer
            df_norm, metadata = self._normalize_table_with_metadata(
                df, heading, table_context
            )

            # Check if normalization succeeded in identifying a Code column
            code_col = metadata.get("code_column")
            if (
                not code_col
                and metadata.get("header_row_idx") == -1
                and not metadata.get("normalization_applied")
            ):
                code_col = next(
                    (c for c in df_norm.columns if str(c).strip().lower() == "code"),
                    None,
                )

            if not code_col:
                from ...utils.table_normalizer import TableNormalizer

                code_col = TableNormalizer._detect_code_column_with_synonyms(df_norm)

            if not code_col:
                canon = metadata.get("canon_report") or {}
                flags = canon.get("flags") or {}
                rule_id = (
                    "UNDETERMINED_HEADER_AFTER_CANONICALIZE"
                    if metadata.get("canonicalization_applied") and flags
                    else "MISSING_CODE_COLUMN"
                )
                return ValidationResult(
                    status="WARN: Cash flows - không tìm thấy cột 'Code' để kiểm tra",
                    marks=[],
                    cross_ref_marks=[],
                    rule_id=rule_id,
                    status_enum="INFO_SKIPPED",
                    context={"failure_reason_code": rule_id, **metadata},
                )

            # Use normalized dataframe
            tmp = df_norm
            header = list(tmp.columns)
            header_idx = -1

            # P2-T1: Ensure we assign the detected columns for downstream use if possible
            # Currently the rest of the code re-detects columns, so we just provide tmp.

            # Identify columns
            code_col = next(
                (c for c in tmp.columns if str(c).strip().lower() == "code"), None
            )
            if code_col is None:
                canon = metadata.get("canon_report") or {}
                flags = canon.get("flags") or {}
                rule_id = (
                    "UNDETERMINED_HEADER_AFTER_CANONICALIZE"
                    if metadata.get("canonicalization_applied") and flags
                    else "MISSING_CODE_COLUMN"
                )
                return ValidationResult(
                    status="WARN: Cash flows - không xác định được cột 'Code'",
                    marks=[],
                    cross_ref_marks=[],
                    rule_id=rule_id,
                    status_enum="INFO_SKIPPED",
                    context={"failure_reason_code": rule_id, **metadata},
                )

            # Find numeric columns using advanced column detection
            cur_col, prior_col = ColumnDetector.detect_financial_columns_advanced(tmp)
            if cur_col is None or prior_col is None:
                return ValidationResult(
                    status="FAIL_TOOL_EXTRACT: Không tìm thấy cặp cột CY/PY có đủ numeric evidence",
                    marks=[],
                    cross_ref_marks=[],
                    rule_id="NO_NUMERIC_EVIDENCE",
                    status_enum="FAIL_TOOL_EXTRACT",
                    context={"failure_reason_code": "NO_NUMERIC_EVIDENCE", **metadata},
                )

            # Build data map for this table using multi-map approach
            from collections import defaultdict

            data_map: Dict[str, List[tuple]] = defaultdict(list)
            rows_cache = []

            for ridx, row in tmp.iterrows():
                code = self._normalize_code(row.get(code_col, ""))
                cur_val = parse_numeric(row.get(cur_col, ""))
                prior_val = parse_numeric(row.get(prior_col, ""))

                # Cache all rows for special case handling
                rows_cache.append((ridx, code, cur_val, prior_val))

                # Only aggregate valid codes at table level
                if code and re.match(r"^[0-9]+[A-Z]?$", code):
                    data_map[code].append((cur_val, prior_val, ridx))

            # Handle special case for Code 18
            target_set = {str(i) for i in range(14, 21)}
            first_block_idx = None
            for ridx, code, _, _ in rows_cache:
                if code in target_set:
                    first_block_idx = ridx
                    break

            if first_block_idx is not None and first_block_idx > 0:
                idx18 = first_block_idx - 1
                prev_code = rows_cache[idx18][1]
                prev_cur = rows_cache[idx18][2]
                prev_pr = rows_cache[idx18][3]

                if (prev_code == "" or prev_code is None) and (
                    abs(prev_cur) + abs(prev_pr) != 0
                ):
                    data_map["18"].append((prev_cur, prev_pr, idx18))

            # Get column positions
            try:
                cur_col_pos = header.index(cur_col)
                prior_col_pos = header.index(prior_col)
            except ValueError:
                cur_col_pos = len(header) - 2
                prior_col_pos = len(header) - 1

            # Flat dictionary for mathematical cross-table aggregations
            flat_data: Dict[str, Tuple[float, float]] = {}
            for c, lst in data_map.items():
                flat_data[c] = (sum(v[0] for v in lst), sum(v[1] for v in lst))

            # P2-1: Optional document-level cross-table aggregation via AuditContext
            flags = get_feature_flags()
            aggregated_data: Dict[str, Tuple[float, float]] = flat_data
            context: Optional[AuditContext] = getattr(self, "context", None)
            if flags.get("cashflow_cross_table_context", False) and context is not None:
                registry = context.cash_flow_registry or {}
                if registry:
                    # Pre-built registry from AuditService: use document-level aggregation
                    aggregated_data = registry
                else:
                    # Backward-compatible sequential merge when no pre-built registry
                    for code, (cur_v, pr_v) in flat_data.items():
                        r_cur, r_pr = registry.get(code, (0.0, 0.0))
                        registry[code] = (r_cur + cur_v, r_pr + pr_v)
                    context.cash_flow_registry = registry
                    aggregated_data = registry

            # Validate cash flow rules using aggregated_data (document-level when enabled)
            issues = []
            marks = []

            def check(parent, children, label=None):
                parent_norm = self._normalize_code(parent)
                if parent_norm not in aggregated_data:
                    return

                have_any, cur_sum, prior_sum, missing = self._sum_weighted(
                    aggregated_data, children
                )
                # SCRUM-12: If no children found but parent exists, treat missing as 0 (WARN instead of FAIL)
                if not have_any:
                    # If parent exists but no children, this might be a missing line item
                    # Return WARN instead of silent skip
                    if missing:
                        issues.append(
                            f"{parent_norm}: Thiếu các thành phần {', '.join(missing)} (treat as 0)"
                        )
                    return

                ac_cur, ac_pr = aggregated_data[parent_norm]
                dc = cur_sum - ac_cur
                dp = prior_sum - ac_pr
                is_ok_cy = abs(round(dc)) == 0
                is_ok_py = abs(round(dp)) == 0

                comment = (
                    f"{parent_norm} = {' + '.join(children).replace('+ -', ' - ')}; "
                    f"Tính={cur_sum:,.0f}/{prior_sum:,.0f}; Thực tế={ac_cur:,.0f}/{ac_pr:,.0f}; Δ={dc:,.0f}/{dp:,.0f}"
                    + (f"; Thiếu={','.join(missing)}" if missing else "")
                )

                if parent_norm in data_map:
                    for _, _, ridx in data_map[parent_norm]:
                        # SCRUM-11: If header_idx = -1, header already promoted, no offset needed
                        df_row = (header_idx + 1 + ridx) if header_idx >= 0 else ridx
                        marks.append(
                            {
                                "row": df_row,
                                "col": cur_col_pos,
                                "ok": is_ok_cy,
                                "comment": None if is_ok_cy else comment,
                            }
                        )
                        marks.append(
                            {
                                "row": df_row,
                                "col": prior_col_pos,
                                "ok": is_ok_py,
                                "comment": None if is_ok_py else comment,
                            }
                        )

                if not is_ok_cy or not is_ok_py:
                    issues.append(comment)

            # Apply cash flow rules
            check("08", ["01", "02", "03", "04", "05", "06", "07"])
            if "18" in data_map:
                check("18", ["08", "09", "10", "11", "12", "13"])
            check("20", ["08", "09", "10", "11", "12", "13", "14", "15", "16", "17"])
            check("30", ["21", "22", "23", "24", "25", "26", "27"])
            check("40", ["31", "32", "33", "34", "35", "36"])
            check("50", ["20", "30", "40"])
            check("70", ["50", "60", "61"])

            # Generate status
            if not issues:
                status = "PASS: Statement of cash flows - kiểm tra công thức: KHỚP (0 sai lệch)"
            else:
                preview = "; ".join(issues[:10])
                more = f" ... (+{len(issues) - 10} dòng)" if len(issues) > 10 else ""
                status = f"FAIL: Statement of cash flows - kiểm tra công thức: {len(issues)} sai lệch. {preview}{more}"

            result = ValidationResult(
                status=status,
                marks=marks,
                cross_ref_marks=[],
                detected_columns=list(tmp.columns),
                root_cause="Calculation Mismatch" if issues else None,
                table_id="Cash Flow",
                assertions_count=len(marks),
                context=metadata,
            )
            result = self._enforce_pass_gating(
                result,
                result.assertions_count,
                metadata.get("numeric_evidence_score", 0.0),
            )
            return self._apply_warn_capping(result, table_context)
        except Exception as e:
            logger.exception("Cash flow validator logic failed")
            return ValidationResult(
                status=f"FAIL: Validator logic error - {type(e).__name__}: {e}",
                marks=[],
                cross_ref_marks=[],
                status_enum="FAIL_TOOL_LOGIC",
                rule_id="FAIL_TOOL_LOGIC_VALIDATOR_CRASH",
                context=dict(table_context) if table_context else {},
                exception_type=type(e).__name__,
                exception_message=str(e),
            )
        finally:
            self._current_table_context = {}

    def _sum_weighted(self, data: Dict[str, tuple], children: List[str]) -> tuple:
        """Calculate weighted sum for cash flow rules."""
        have_any = False
        cur_sum = prior_sum = 0.0
        missing = []

        for token in children:
            token = str(token).strip()
            sign = 1  # Cash flow rules are typically additive
            code = token
            cn = self._normalize_code(code)

            if cn in data:
                ccur, cprior = data[cn]
                cur_sum += sign * ccur
                prior_sum += sign * cprior
                have_any = True
            else:
                missing.append(cn)

        return have_any, cur_sum, prior_sum, missing
