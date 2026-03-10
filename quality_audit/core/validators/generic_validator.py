"""
Generic table validator for standard financial tables.
"""

import logging
import re
from typing import Dict, List, Optional, Sequence, Tuple, Union

import pandas as pd

from ...config.constants import (
    CROSS_CHECK_TABLES_FORM_1,
    CROSS_CHECK_TABLES_FORM_2,
    CROSS_CHECK_TABLES_FORM_3,
    FAIL_TOOL_EXTRACT_MISSING_PERIOD_COLUMN,
    FAIL_TOOL_EXTRACT_NO_NUMERIC,
    FAIL_TOOL_EXTRACT_NO_TOTALS,
    GATE_REASON_NO_DETAIL_ROWS,
    GATE_REASON_NO_NUMERIC_COLUMNS,
    GATE_REASON_NO_TOTAL_ROW_MATCH,
    TABLES_NEED_CHECK_SEPARATELY,
    TABLES_NEED_COLUMN_CHECK,
    TABLES_WITHOUT_TOTAL,
)
from ...config.feature_flags import get_feature_flags
from ...utils.column_detector import ColumnDetector
from ...utils.column_roles import (
    ROLE_CODE,
    ROLE_NUMERIC,
    get_columns_to_exclude_from_sum,
    infer_column_roles,
)
from ...utils.numeric_utils import (
    compare_amounts,
    compute_numeric_evidence_score,
    is_year_like_value,
    normalize_numeric_column,
)
from ...utils.skip_classifier import classify_footer_signature
from ..cache_manager import cross_check_marks
from .base_validator import BaseValidator, ValidationResult

logger = logging.getLogger(__name__)

FORMULA_KEYWORDS = [
    r"(?i)x\s*\d+(?:\.\d+)?\s*%",
    r"(?i)\*\s*\d+(?:\.\d+)?\s*%",
    r"(?i)\b\d+(?:\.\d+)?\s*%\s*x\b",
    r"(?i)tỷ lệ\b",
    r"(?i)thuế suất",
    r"(?i)phần vượt mức",
    r"(?i)định mức",
    r"(?i)nhân với",
]


class GenericTableValidator(BaseValidator):
    """Generic validator for standard financial tables."""

    def _deduplicate_marks(
        self,
        marks: List[Dict],
        cross_ref_marks: List[Dict],
        *,
        is_table_fail: bool,
    ) -> Tuple[List[Dict], List[Dict]]:
        """
        Deduplicate/resolve conflicts among validation marks and cross-ref marks.

        Priority rules (tested):
        - Within the same (row,col): FAIL (ok=False) overrides PASS.
        - If table is FAIL: strip PASS marks in both lists.
        - Cross-ref FAIL overrides validation PASS at same (row,col).
        - Validation FAIL overrides cross-ref PASS at same (row,col).
        """

        def _collapse_same_pos(items: List[Dict]) -> Dict[Tuple[int, int], Dict]:
            by_pos: Dict[Tuple[int, int], Dict] = {}
            for m in items or []:
                pos = (int(m.get("row", -1)), int(m.get("col", -1)))
                if pos not in by_pos:
                    by_pos[pos] = m
                    continue
                prev = by_pos[pos]
                prev_ok = prev.get("ok")
                cur_ok = m.get("ok")
                # Prefer FAIL over PASS
                if prev_ok is False:
                    continue
                if cur_ok is False:
                    by_pos[pos] = m
                    continue
                # Both PASS/unknown: keep first (stable)
            return by_pos

        m_by_pos = _collapse_same_pos(marks)
        c_by_pos = _collapse_same_pos(cross_ref_marks)

        if is_table_fail:
            m_by_pos = {p: m for p, m in m_by_pos.items() if m.get("ok") is False}
            c_by_pos = {p: m for p, m in c_by_pos.items() if m.get("ok") is False}

        # Resolve cross-list conflicts
        for pos in list(set(m_by_pos.keys()) & set(c_by_pos.keys())):
            m_ok = m_by_pos[pos].get("ok")
            c_ok = c_by_pos[pos].get("ok")
            # Validation FAIL dominates cross-ref PASS (drop cross-ref)
            if m_ok is False and c_ok is True:
                del c_by_pos[pos]
            # Cross-ref FAIL dominates validation PASS (drop validation)
            elif m_ok is True and c_ok is False:
                del m_by_pos[pos]

        cleaned_marks = [m_by_pos[p] for p in sorted(m_by_pos.keys())]
        cleaned_cross = [c_by_pos[p] for p in sorted(c_by_pos.keys())]
        return cleaned_marks, cleaned_cross

    def validate(
        self,
        df: pd.DataFrame,
        heading: Optional[str] = None,
        table_context: Optional[Dict] = None,
    ) -> ValidationResult:
        """
        Validate generic financial table.

        Args:
            df: DataFrame containing table data
            heading: Table heading for context
            table_context: Optional extraction metadata (quality_score, quality_flags)

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
            heading_lower = heading.lower().strip() if heading else ""

            # Check for special table types that should be skipped
            if self._should_skip_table(df, heading_lower):
                return ValidationResult(
                    status="INFO: Bảng không bao gồm số/số tổng",
                    marks=[],
                    cross_ref_marks=[],
                    rule_id="TABLE_NO_NUMERIC_STRUCTURE",
                    status_enum="INFO_SKIPPED",
                    context={"failure_reason_code": "TABLE_NO_NUMERIC_STRUCTURE"},
                )

            # Standard table validation
            return self._validate_standard_table(df, heading_lower, table_context)
        except Exception as e:
            logger.exception("Validator logic failed")
            return ValidationResult(
                status="FAIL_TOOL_LOGIC: Validator exception",
                marks=[],
                cross_ref_marks=[],
                rule_id="FAIL_TOOL_LOGIC_VALIDATOR_CRASH",
                status_enum="FAIL_TOOL_LOGIC",
                context=dict(table_context) if table_context else {},
                exception_type=type(e).__name__,
                exception_message=str(e),
            )
        finally:
            self._current_table_context = {}

    def _evaluate_text_formula(
        self,
        df: pd.DataFrame,
        df_numeric: pd.DataFrame,
        code_cols_set: set,
    ) -> Optional[ValidationResult]:
        """Track 3: Basic parsing of specific text formulas (e.g. x 20% or A = B + C)."""
        import re

        from ...utils.numeric_utils import is_year_like_value

        marks = []
        issues = []
        evaluated_assertions = 0

        pct_pattern = re.compile(r"(?i)[x\*]\s*(\d+(?:\.\d+)?)\s*%")

        # 1. Percentage formula (x 20% or * 20%)
        # Scanning from the second row onwards because it refers to the previous row
        for i in range(1, len(df)):
            cell_text = str(df.iloc[i, 0]).strip()
            m = pct_pattern.search(cell_text)
            if m:
                pct = float(m.group(1)) / 100.0

                for col_idx, col_name in enumerate(df.columns):
                    if col_name in code_cols_set:
                        continue

                    val = df_numeric.iloc[i, col_idx]
                    prev_val = df_numeric.iloc[i - 1, col_idx]

                    if pd.isna(val) or pd.isna(prev_val):
                        continue

                    if is_year_like_value(val) or is_year_like_value(prev_val):
                        continue

                    expected = prev_val * pct
                    diff = expected - val
                    is_ok, _, _, _ = compare_amounts(expected, val)

                    evaluated_assertions += 1

                    if is_ok:
                        marks.append(
                            {
                                "row": i,
                                "col": col_idx,
                                "ok": True,
                                "rule_id": "TEXT_FORMULA_PERCENTAGE",
                            }
                        )
                    else:
                        comment = (
                            f"Cột {col_idx + 1}: Tính theo công thức {pct * 100:g}% "
                            f"= {expected:,.2f}, thực tế = {val:,.2f}, lệch {diff:,.2f}"
                        )
                        marks.append(
                            {
                                "row": i,
                                "col": col_idx,
                                "ok": False,
                                "comment": comment,
                                "rule_id": "TEXT_FORMULA_PERCENTAGE",
                            }
                        )
                        issues.append(comment)

        # 2. Additive formulas (A = B [+-] C) based on codes
        eq_pattern = re.compile(
            r"\(?(\d{1,3})\)?\s*=\s*\(?(\d{1,3})\)?\s*([\+\-])\s*\(?(\d{1,3})\)?"
        )

        # Build mapping of "Code" -> row index if exists
        code_map = {}
        if code_cols_set:
            code_col = list(code_cols_set)[0]
            for r in range(len(df)):
                code_val = str(df.iloc[r][code_col]).strip()
                # Remove parens and extra spaces
                code_val_clean = re.sub(r"[^\d]", "", code_val)
                if code_val_clean:
                    code_map[code_val_clean] = r

        for i in range(len(df)):
            cell_text = str(df.iloc[i, 0]).strip()
            m = eq_pattern.search(cell_text)
            if m:
                target_id = m.group(1)
                op1_id = m.group(2)
                operator = m.group(3)
                op2_id = m.group(4)

                # Resolve row indices
                target_r = code_map.get(target_id)
                op1_r = code_map.get(op1_id)
                op2_r = code_map.get(op2_id)

                if target_r is None or op1_r is None or op2_r is None:
                    continue

                for col_idx, col_name in enumerate(df.columns):
                    if col_name in code_cols_set:
                        continue

                    target_val = df_numeric.iloc[target_r, col_idx]
                    op1_val = df_numeric.iloc[op1_r, col_idx]
                    op2_val = df_numeric.iloc[op2_r, col_idx]

                    if pd.isna(target_val) or pd.isna(op1_val) or pd.isna(op2_val):
                        continue

                    if is_year_like_value(target_val):
                        continue

                    if operator == "+":
                        expected = op1_val + op2_val
                    else:
                        expected = op1_val - op2_val

                    diff = expected - target_val
                    is_ok, _, _, _ = compare_amounts(expected, target_val)

                    evaluated_assertions += 1

                    if is_ok:
                        marks.append(
                            {
                                "row": target_r,
                                "col": col_idx,
                                "ok": True,
                                "rule_id": "TEXT_FORMULA_EQUATION",
                            }
                        )
                    else:
                        comment = (
                            f"Cột {col_idx + 1}: Tính theo công thức {cell_text} "
                            f"= {expected:,.2f}, thực tế = {target_val:,.2f}, lệch {diff:,.2f}"
                        )
                        marks.append(
                            {
                                "row": target_r,
                                "col": col_idx,
                                "ok": False,
                                "comment": comment,
                                "rule_id": "TEXT_FORMULA_EQUATION",
                            }
                        )
                        issues.append(comment)

        if evaluated_assertions > 0:
            status_enum = "FAIL" if issues else "PASS"
            status_str = (
                f"FORMULA_EVALUATED: {len(issues)} issues found"
                if issues
                else "PASS: Công thức text khớp"
            )
            return ValidationResult(
                status=status_str,
                marks=marks,
                cross_ref_marks=[],
                status_enum=status_enum,
                context={"issues": issues},
                assertions_count=evaluated_assertions,
            )

        return None

    def _should_skip_table(self, df: pd.DataFrame, heading_lower: str) -> bool:
        """Check if table should be skipped from validation.
        Spine 3: When table is all non-numeric, use 2-phase classifier; only skip when
        footer/signature evidence is strong and financial-table evidence is weak.
        """
        # Patch E: case-insensitive match for TABLES_WITHOUT_TOTAL
        if heading_lower in TABLES_WITHOUT_TOTAL or any(
            heading_lower == t.lower() for t in TABLES_WITHOUT_TOTAL
        ):
            return True

        subset = df.iloc[0:]
        numeric_content = subset.map(
            lambda x: pd.to_numeric(
                str(x).replace(",", "").replace("(", "-").replace(")", ""),
                errors="coerce",
            )
        )
        all_non_numeric = bool(numeric_content.isna().all().all())
        if not all_non_numeric:
            return False
        should_skip, evidence = classify_footer_signature(df, heading=heading_lower)
        if not should_skip:
            logger.debug(
                "generic_validator: all non-numeric but 2-phase says do not skip. "
                "negative_hits=%s",
                len(evidence.get("negative_hits", [])),
            )
        return should_skip

    def _validate_standard_table(
        self,
        df: pd.DataFrame,
        heading_lower: str,
        table_context: Optional[Dict] = None,
    ) -> ValidationResult:
        """Validate standard table with totals.
        Pattern A fix: Fallback Code detection when _detect_code_column returns None.
        Multi-code: when multi_code_columns_exclusion is on, exclude all Code/Code.1/... from sums.
        """
        flags = get_feature_flags()
        code_col: Optional[str] = None
        code_cols: List[str] = []
        code_col_detection_method: str = "none"
        exclude_for_totals_list: List[str] = []
        roles: Dict[str, str] = {}
        evidence: Dict = {}
        if flags.get("generic_exclude_code_columns", True):
            roles, _, evidence = infer_column_roles(
                df, header_row=0, context=table_context or {}
            )
            code_cols = [c for c, r in roles.items() if r == ROLE_CODE]
            code_col = code_cols[0] if code_cols else None
            exclude_for_totals_list = get_columns_to_exclude_from_sum(
                roles, include_note=True
            )
            if code_cols:
                code_col_detection_method = "role_based"
            logger.debug(
                "Code column detection: code_cols=%s, source=%s",
                code_cols,
                code_col_detection_method,
            )
            if code_cols:
                logger.info(
                    "Table %s: excluded code columns (n=%d): %s, method=%s",
                    heading_lower[:50] if heading_lower else "unknown",
                    len(code_cols),
                    code_cols,
                    code_col_detection_method,
                )
            if not code_cols and df is not None and not df.empty:
                logger.debug("No ROLE_CODE columns; columns: %s", list(df.columns))

            # Spine fix 2: Evidence gate — no ROLE_NUMERIC => NO_EVIDENCE (no sum/compare)
            chosen_numeric = evidence.get("chosen_numeric_columns") or []
            if not chosen_numeric and not df.empty:
                gate_ctx = dict(table_context) if table_context else {}
                gate_ctx["gate_decision"] = "NO_EVIDENCE"
                gate_ctx["failure_reason_code"] = GATE_REASON_NO_NUMERIC_COLUMNS
                gate_ctx["evidence"] = {
                    "chosen_numeric_columns": chosen_numeric,
                    "excluded_code_columns": evidence.get("excluded_code_columns", []),
                }
                logger.info(
                    "Evidence gate: no numeric columns for table %s, gate_decision=NO_EVIDENCE",
                    heading_lower[:50] if heading_lower else "unknown",
                )
                return ValidationResult(
                    status="FAIL_TOOL_EXTRACT: No numeric columns to validate",
                    marks=[],
                    cross_ref_marks=[],
                    rule_id=FAIL_TOOL_EXTRACT_NO_NUMERIC,
                    status_enum="FAIL_TOOL_EXTRACT",
                    context=gate_ctx,
                )

            # Spine fix 2: No detail rows (only header or empty) => NO_EVIDENCE
            if len(df) <= 1:
                gate_ctx = dict(table_context) if table_context else {}
                gate_ctx["gate_decision"] = "NO_EVIDENCE"
                gate_ctx["failure_reason_code"] = GATE_REASON_NO_DETAIL_ROWS
                gate_ctx["evidence"] = {"row_count": len(df)}
                return ValidationResult(
                    status="INFO: No detail rows to validate",
                    marks=[],
                    cross_ref_marks=[],
                    rule_id="TABLE_EMPTY",
                    status_enum="INFO",
                    context=gate_ctx,
                )

        if code_cols:
            df_numeric = self._convert_to_numeric_df_excluding_code(
                df, code_cols=code_cols
            )
        else:
            df_numeric = df.astype(object).map(normalize_numeric_column)

        # Track 1: Calculation Mode Guardrail
        # Check if table label columns contain formula indicators
        text_cols_to_check = []
        if len(df.columns) > 0:
            text_cols_to_check.append(df.columns[0])

        is_formula_table = False
        for col in text_cols_to_check:
            col_series = df[col].astype(str).str.strip()
            # We require the keyword to be on a detail row to trigger the skip
            for _idx, cell_text in col_series.items():
                if any(re.search(pat, cell_text) for pat in FORMULA_KEYWORDS):
                    is_formula_table = True
                    logger.info(
                        "Table %s skipped due to formula matching: '%s' matched in column",
                        heading_lower[:50] if heading_lower else "unknown",
                        cell_text,
                    )
                    break
            if is_formula_table:
                break

        if is_formula_table:
            eval_result = self._evaluate_text_formula(
                df, df_numeric, set(code_cols) if code_cols else set()
            )
            if eval_result:
                return eval_result

            return ValidationResult(
                status="INFO: Bảng chứa công thức nghiệp vụ (tỷ lệ/giới hạn), bỏ qua auto-sum",
                marks=[],
                cross_ref_marks=[],
                status_enum="INFO_SKIPPED",
                context={"no_assertion_reason": "FORMULA_TABLE"},
                assertions_count=0,
            )

        note_col = None
        if self.context:
            meta = self.context.get_last_normalization_metadata()
            if meta:
                note_col = meta.get("note_column")
        if note_col is None:
            note_col = ColumnDetector.detect_note_column(df)
        if exclude_for_totals_list:
            exclude_for_totals = list(
                dict.fromkeys(
                    exclude_for_totals_list + ([note_col] if note_col else [])
                )
            )
        else:
            exclude_for_totals = list(code_cols or []) + (
                [note_col] if note_col else []
            )

        total_row_idx = self._find_total_row(df, code_cols=exclude_for_totals)
        amount_cols = self._detect_amount_columns(df, code_cols=exclude_for_totals)

        # A3: movement/reconciliation gating (heuristic); Phase 4: extended movement_terms
        movement_terms = [
            "movement",
            "reconciliation",
            "opening balance",
            "closing balance",
            "addition",
            "additions",
            "paid",
            "payment",
            "transfer",
            "decrease",
            "increase",
            "phát sinh",
            "số đầu",
            "số cuối",
            "tăng",
            "giảm",
            "chuyển",
            "nộp",
            "brought forward",
            "carried forward",
            "disposal",
            "disposals",
            "acquisition",
            "depreciation",
            "số chuyển",
            "đầu kỳ",
            "cuối kỳ",
        ]
        if flags.get("movement_rollforward", False):
            movement_structure = self._detect_movement_structure(df)
        else:
            movement_structure = None
        heading_text = heading_lower or ""
        header_text = " ".join(str(c).lower() for c in df.columns)
        is_movement_table = (
            any(t in heading_text for t in movement_terms)
            or any(t in header_text for t in movement_terms)
            or (
                movement_structure is not None
                and flags.get("movement_rollforward", False)
            )
        )

        if total_row_idx is None and not self._needs_column_check(heading_lower):
            return ValidationResult(
                status="INFO: Bảng không có dòng/cột tổng",
                marks=[],
                cross_ref_marks=[],
                rule_id="TABLE_NO_TOTAL_ROW",
                status_enum="INFO",
                context={"failure_reason_code": "NO_TOTAL_AND_NO_COLUMN_CHECK"},
            )

        # Phase 4.3: No totals found but table needs totals → policy: structural unreliability → FAIL_TOOL_EXTRACT; else WARN
        if total_row_idx is None:
            quality_score = (table_context or {}).get("quality_score")
            quality_flags = (table_context or {}).get("quality_flags") or []
            bad_flags = {"GRID_CORRUPTION", "DUPLICATE_PERIODS"}
            structural_unreliable = (
                quality_score is not None and quality_score < 0.6
            ) or any(f in bad_flags for f in quality_flags)
            ctx = dict(table_context) if table_context else {}
            ctx["failure_reason_code"] = GATE_REASON_NO_TOTAL_ROW_MATCH
            ctx["gate_decision"] = "NO_TOTAL_ROW_MATCH"
            ctx.setdefault(
                "evidence",
                {"total_row_idx": None, "amount_cols": amount_cols},
            )
            if structural_unreliable:
                return ValidationResult(
                    status="FAIL_TOOL_EXTRACT: Không tìm thấy dòng tổng (cấu trúc bảng không đáng tin)",
                    marks=[],
                    cross_ref_marks=[],
                    rule_id=FAIL_TOOL_EXTRACT_NO_TOTALS,
                    status_enum="FAIL_TOOL_EXTRACT",
                    context=ctx,
                )
            return ValidationResult(
                status="WARN: Không tìm thấy dòng tổng phù hợp",
                marks=[],
                cross_ref_marks=[],
                rule_id="TABLE_NO_TOTAL_ROW",
                status_enum="WARN",
                context=ctx,
            )

        last_col_idx = len(df.columns) - 1
        check_column_total = heading_lower in [
            name.lower() for name in TABLES_NEED_COLUMN_CHECK
        ]
        check_separately_total = heading_lower in [
            name.lower() for name in TABLES_NEED_CHECK_SEPARATELY
        ]

        # Phase 4: Evidence gate before column-total validation (skip for fixed-assets / check_separately_total)
        run_column_totals = (
            check_column_total and last_col_idx > 1 and total_row_idx is not None
        )
        if (
            run_column_totals
            and not check_separately_total
            and flags.get("generic_evidence_gate", False)
        ):
            header_str = (
                str(df.columns[last_col_idx]).lower() if last_col_idx >= 0 else ""
            )
            first_col_has_label = False
            if len(df) > 0 and len(df.columns) > 0:
                first_col_vals = df.iloc[:, 0].astype(str)
                non_empty = (first_col_vals.str.strip() != "").sum()
                first_col_has_label = non_empty >= 1
            total_like = any(
                t in header_str for t in ("total", "sum", "tổng", "amount", "cộng")
            ) or bool(re.search(r"20\d{2}", header_str))
            if not (total_like and first_col_has_label):
                run_column_totals = False
                logger.debug(
                    "generic_evidence_gate: skip column totals (header=%s, first_col_has_label=%s)",
                    header_str[:50],
                    first_col_has_label,
                )
                # Comment 4: early return with INFO when evidence gate disables column totals
                return ValidationResult(
                    status="INFO: Bỏ qua kiểm tra cột tổng (không đủ bằng chứng)",
                    marks=[],
                    cross_ref_marks=[],
                    status_enum="INFO",
                    context={
                        "no_total_evidence_skip": True,
                        "generic_evidence_gate": True,
                    },
                    assertions_count=0,
                )

        # Eligibility gate (enable_generic_total_gate): avoid COLUMN_TOTAL_VALIDATION on unsuitable tables
        if (
            run_column_totals
            and not check_separately_total
            and flags.get("enable_generic_total_gate", False)
        ):
            detail_count = 0
            for i in range(total_row_idx):
                row = df.iloc[i]
                for c in amount_cols:
                    if c not in df.columns:
                        continue
                    try:
                        v = row.get(c)
                        if pd.notna(v) and not is_year_like_value(v):
                            float(v)
                            detail_count += 1
                            break
                    except (TypeError, ValueError):
                        pass
            total_row_label = ""
            if total_row_idx < len(df) and len(df.columns) > 0:
                total_row_label = str(df.iloc[total_row_idx, 0]).strip().lower()
            _total_keywords = (
                "total",
                "subtotal",
                "grand total",
                "tổng",
                "tổng cộng",
                "cộng",
            )
            has_total_keyword = any(k in total_row_label for k in _total_keywords)
            if flags.get("tighten_total_row_keywords", False):
                line_item_hints = (
                    "profit",
                    "income",
                    "expense",
                    "lợi nhuận",
                    "doanh thu",
                    "chi phí",
                )
                has_line_item_no_total = (
                    any(h in total_row_label for h in line_item_hints)
                    and not has_total_keyword
                )
            else:
                has_line_item_no_total = False
            gate_fail_reason = None
            if detail_count < 2:
                gate_fail_reason = "insufficient_detail_rows"
            elif not has_total_keyword and not (
                total_row_label.startswith("total ")
                or total_row_label.startswith("tổng ")
            ):
                gate_fail_reason = "total_row_label_mismatch"
            elif has_line_item_no_total:
                gate_fail_reason = "statement_like_line_item"
            # When total row was selected by row_classifier, trust it and skip label_mismatch gate
            if (
                gate_fail_reason == "total_row_label_mismatch"
                and self.context
                and hasattr(self.context, "get_last_total_row_metadata")
            ):
                _tr_meta = self.context.get_last_total_row_metadata()
                if _tr_meta and _tr_meta.get("method") == "row_classifier":
                    gate_fail_reason = None
            # Enrich total_row_metadata for observability (total_row_label_preview, gate_decision)
            if (
                self.context
                and hasattr(self.context, "get_last_total_row_metadata")
                and hasattr(self.context, "set_last_total_row_metadata")
            ):
                _tr_meta = self.context.get_last_total_row_metadata()
                if _tr_meta:
                    _tr_meta = dict(_tr_meta)
                    _tr_meta["total_row_label_preview"] = (
                        total_row_label[:80] if total_row_label else ""
                    )
                    _tr_meta["gate_decision"] = (
                        "pass" if gate_fail_reason is None else gate_fail_reason
                    )
                    self.context.set_last_total_row_metadata(_tr_meta)
            if gate_fail_reason is not None:
                logger.info(
                    "generic_total_gate: skip COLUMN_TOTAL (table_id=%s) reason=%s detail_count=%s total_label=%s",
                    (table_context or {}).get("table_id", ""),
                    gate_fail_reason,
                    detail_count,
                    total_row_label[:40] if total_row_label else "",
                )
                return ValidationResult(
                    status=f"INFO: Rule not applicable (eligibility gate: {gate_fail_reason})",
                    marks=[],
                    cross_ref_marks=[],
                    status_enum="INFO",
                    context={
                        "no_assertion_reason": "ELIGIBILITY_GATE",
                        "eligibility_gate_reason": gate_fail_reason,
                        "detail_count": detail_count,
                        "total_row_label_preview": (
                            total_row_label[:80] if total_row_label else ""
                        ),
                    },
                    assertions_count=0,
                )

        issues: List[str] = []
        marks: List[Dict] = []
        cross_ref_marks: List[Dict] = []

        # Comment 1: When movement_rollforward is on, run roll-forward before other total checks.
        # If roll-forward has insufficient data (missing OB/CB or no numeric OB/CB), return INFO early.
        if (
            movement_structure is not None
            and flags.get("movement_rollforward", False)
            and amount_cols
        ):
            ob_row = movement_structure.get("ob_row")
            cb_row = movement_structure.get("cb_row")
            if ob_row is None or cb_row is None:
                return ValidationResult(
                    status="INFO: Bỏ qua kiểm tra roll-forward (thiếu OB/CB)",
                    marks=[],
                    cross_ref_marks=[],
                    status_enum="INFO",
                    context={"rollforward_skip_reason": "missing_ob_cb"},
                    assertions_count=0,
                )
            has_numeric_ob_cb = False
            for col in amount_cols:
                try:
                    ob_v = pd.to_numeric(df_numeric.loc[ob_row, col], errors="coerce")
                    cb_v = pd.to_numeric(df_numeric.loc[cb_row, col], errors="coerce")
                    if pd.notna(ob_v) and pd.notna(cb_v):
                        has_numeric_ob_cb = True
                        break
                except (KeyError, TypeError):
                    continue
            if not has_numeric_ob_cb:
                return ValidationResult(
                    status="INFO: Bỏ qua kiểm tra roll-forward (không có dữ liệu số OB/CB)",
                    marks=[],
                    cross_ref_marks=[],
                    status_enum="INFO",
                    context={"rollforward_skip_reason": "no_numeric_ob_cb"},
                    assertions_count=0,
                )
            self._validate_rollforward(
                df_numeric, movement_structure, amount_cols, marks, issues
            )

        if check_separately_total:
            # Fixed assets validation (simplified)
            result = self._validate_fixed_assets(df, df_numeric, heading_lower)
            return result
        elif run_column_totals:
            # Column total validation (evidence gate applied above when flag on)
            self._validate_column_totals(
                df_numeric,
                total_row_idx,
                last_col_idx,
                marks,
                issues,
                code_col=code_col,
                code_cols=code_cols,
            )
        elif total_row_idx is not None:
            # Eligibility gate for row total validation on tables with insufficient detail rows.
            # Mirrors enable_generic_total_gate semantics for column totals, but applied to row totals path.
            if flags.get("enable_generic_total_gate", False) and amount_cols:
                detail_count = 0
                for i in range(0, total_row_idx):
                    if i >= len(df_numeric):
                        break
                    for c in amount_cols:
                        if c not in df_numeric.columns:
                            continue
                        v = df_numeric.loc[df_numeric.index[i], c]
                        if pd.notna(v) and not is_year_like_value(v):
                            detail_count += 1
                            break
                if detail_count < 2:
                    total_row_label = ""
                    if total_row_idx < len(df) and len(df.columns) > 0:
                        total_row_label = str(df.iloc[total_row_idx, 0]).strip().lower()
                    logger.info(
                        "generic_total_gate: skip ROW_TOTAL (table_id=%s) reason=%s detail_count=%s total_label=%s",
                        (table_context or {}).get("table_id", ""),
                        "insufficient_detail_rows",
                        detail_count,
                        total_row_label[:40] if total_row_label else "",
                    )
                    return ValidationResult(
                        status="INFO: Rule not applicable (eligibility gate: insufficient_detail_rows)",
                        marks=[],
                        cross_ref_marks=[],
                        status_enum="INFO",
                        context={
                            "no_assertion_reason": "ELIGIBILITY_GATE",
                            "eligibility_gate_reason": "insufficient_detail_rows",
                            "detail_count": detail_count,
                            "total_row_label_preview": (
                                total_row_label[:80] if total_row_label else ""
                            ),
                        },
                        assertions_count=0,
                    )
            # Standard row total validation
            self._validate_row_totals(
                df,
                df_numeric,
                total_row_idx,
                code_col,
                heading_lower,
                marks,
                issues,
                cross_ref_marks,
                code_cols=code_cols,
                amount_cols=amount_cols,
            )

        # P3.1: When status would be INFO (no issues but zero assertions), try sum-to-total.
        # If at least one pair of numeric columns and a total row, sum detail rows vs total; if match, set PASS.
        if (
            not issues
            and len(marks) == 0
            and len(cross_ref_marks) == 0
            and total_row_idx is not None
            and total_row_idx >= 0
            and total_row_idx < len(df_numeric)
            and amount_cols
            and len(amount_cols) >= 1
        ):
            # P3.2: Include row if at least one amount column has a numeric value (don't exclude for single-column '-').
            detail_indices = []
            for i in range(0, total_row_idx):
                if i >= len(df_numeric):
                    break
                for col in amount_cols:
                    if col not in df_numeric.columns:
                        continue
                    v = df_numeric.loc[df_numeric.index[i], col]
                    if pd.notna(v) and not is_year_like_value(v):
                        detail_indices.append(i)
                        break
            if detail_indices:
                total_row = df_numeric.iloc[total_row_idx]
                all_match = True
                for col in amount_cols:
                    if col not in df_numeric.columns:
                        continue
                    sum_val = float(
                        df_numeric.loc[df_numeric.index[detail_indices], col].sum()
                    )
                    total_val = total_row[col]
                    if pd.isna(total_val):
                        all_match = False
                        break
                    is_ok, _, _, _ = compare_amounts(sum_val, float(total_val))
                    if not is_ok:
                        all_match = False
                        break
                if all_match:
                    for col in amount_cols:
                        if col not in df_numeric.columns:
                            continue
                        col_idx = df.columns.get_loc(col)
                        marks.append(
                            {
                                "row": total_row_idx,
                                "col": col_idx,
                                "ok": True,
                                "comment": None,
                                "rule_id": "SUM_TO_TOTAL_P3",
                            }
                        )
                    logger.info(
                        "Table %s: sum-to-total (P3.1) matched; added %d assertions",
                        heading_lower[:50] if heading_lower else "unknown",
                        len(marks),
                    )

        # Generate status
        if not issues:
            status = "PASS: Kiểm tra công thức: KHỚP (0 sai lệch)"
        else:
            preview = "; ".join(issues[:10])
            more = f" ... (+{len(issues) - 10} dòng)" if len(issues) > 10 else ""
            if is_movement_table:
                status = (
                    f"WARN: Bảng movement/reconciliation — bỏ qua FAIL sum-check (downgraded). "
                    f"{len(issues)} sai lệch. {preview}{more}"
                )
            else:
                status = (
                    f"FAIL: Kiểm tra công thức: {len(issues)} sai lệch. {preview}{more}"
                )

        # SCRUM-8: Clean up visual conflicts and dedupe marks
        marks, cross_ref_marks = self._deduplicate_marks(
            marks,
            cross_ref_marks,
            is_table_fail=(not is_movement_table and bool(issues)),
        )

        # Phase 6.1: Explicit status_enum for taxonomy (PASS / FAIL / WARN)
        if not issues:
            status_enum_val = "PASS"
        elif is_movement_table:
            status_enum_val = "WARN"
        else:
            status_enum_val = "FAIL"

        # Phase 4: PASS only when assertions_count > 0 (plan DoD); policy via treat_no_assertion_as_pass
        assertions_count = len(marks) + len(cross_ref_marks)
        no_assertion_reason = None
        if status_enum_val == "PASS" and assertions_count == 0:
            flags = get_feature_flags()
            if flags.get("treat_no_assertion_as_pass", False):
                status = "PASS: No applicable assertions (treated as PASS by policy)"
                no_assertion_reason = "NOT_APPLICABLE"
            else:
                status_enum_val = "INFO"
                status = "INFO: Không có assertion nào được thực thi (bảng không đủ bằng chứng để kiểm tra)"
                no_assertion_reason = "NO_EVIDENCE"

        # Comment 1: Compute numeric evidence locally on numeric view (exclude code/note).
        # Use same exclude set as for total row and amount cols (role-based when available).
        exclude_cols = set(exclude_for_totals)
        candidate_cols = (
            amount_cols
            if amount_cols
            else [c for c in df_numeric.columns if c not in exclude_cols]
        )
        evidence = compute_numeric_evidence_score(
            df_numeric, candidate_columns=candidate_cols
        )
        local_numeric_score = evidence.get("numeric_evidence_score", 0.0)
        ctx_from_table = table_context or {}
        gate_score = (
            ctx_from_table["numeric_evidence_score"]
            if "numeric_evidence_score" in ctx_from_table
            else local_numeric_score
        )

        ctx_dict = {
            "excluded_columns": exclude_for_totals,
            "code_col_detection_method": code_col_detection_method,
            "code_col_name": code_col,
            "amount_columns": amount_cols,
            "is_movement_table": is_movement_table,
            "numeric_evidence_score": gate_score,
            "numeric_evidence_per_column": evidence.get("per_column", {}),
            "numeric_col_candidates": evidence.get("numeric_col_candidates", []),
        }
        # Attach total_row_metadata so audit_service uses validator's metadata (avoids cross-table contamination)
        if self.context and hasattr(self.context, "get_last_total_row_metadata"):
            _tr_meta = self.context.get_last_total_row_metadata()
            if _tr_meta:
                ctx_dict["total_row_metadata"] = _tr_meta
        if no_assertion_reason is not None:
            ctx_dict["no_assertion_reason"] = no_assertion_reason
        result = ValidationResult(
            status=status,
            marks=marks,
            cross_ref_marks=cross_ref_marks,
            rule_id="COLUMN_TOTAL_VALIDATION",
            status_enum=status_enum_val,
            context=ctx_dict,
            assertions_count=assertions_count,
        )
        # Phase 4.2: Escalate to FAIL_TOOL_EXTRACT when low score is due to missing period columns
        expected_period_cols = 2
        actual_numeric_cols = (
            len(amount_cols)
            if amount_cols
            else len(evidence.get("numeric_col_candidates", []))
        )
        if gate_score < 0.25 and actual_numeric_cols < expected_period_cols:
            # Ticket-3: Bypass CY/PY gate when movement/roll-forward structure detected
            movement_structure = self._detect_movement_structure(df_numeric)
            if movement_structure is not None and is_movement_table:
                # Run roll-forward validation instead of failing
                logger.info(
                    "Ticket-3: Bypassing CY/PY gate for movement table (gate_score=%.3f)",
                    gate_score,
                )
                rf_issues: List[str] = []
                rf_marks: List[Dict] = []
                self._validate_rollforward(
                    df_numeric,
                    movement_structure,
                    amount_cols if amount_cols else list(df_numeric.columns),
                    rf_marks,
                    rf_issues,
                )
                if rf_issues:
                    rf_preview = "; ".join(rf_issues[:5])
                    rf_status = (
                        f"FAIL: Roll-forward {len(rf_issues)} sai lệch. {rf_preview}"
                    )
                    rf_enum = "FAIL"
                else:
                    rf_status = "PASS: Roll-forward OB + movements ≈ CB: KHỚP"
                    rf_enum = "PASS"
                result = ValidationResult(
                    status=rf_status,
                    marks=rf_marks,
                    cross_ref_marks=cross_ref_marks,
                    rule_id="ROLLFORWARD_VALIDATION",
                    status_enum=rf_enum,
                    context={
                        **ctx_dict,
                        "bypass_reason": "movement_structure_detected",
                        "movement_structure": movement_structure,
                    },
                    assertions_count=len(rf_marks),
                )
            else:
                result = ValidationResult(
                    status=(
                        f"FAIL_TOOL_EXTRACT: Missing period columns "
                        f"(expected {expected_period_cols}, found {actual_numeric_cols})"
                    ),
                    marks=marks,
                    cross_ref_marks=cross_ref_marks,
                    rule_id=FAIL_TOOL_EXTRACT_MISSING_PERIOD_COLUMN,
                    status_enum="FAIL_TOOL_EXTRACT",
                    context={
                        **ctx_dict,
                        "failure_reason_code": "MISSING_PERIOD_COLUMN",
                        "expected_columns": expected_period_cols,
                        "actual_columns": actual_numeric_cols,
                    },
                    assertions_count=assertions_count,
                )
        else:
            result = self._enforce_pass_gating(
                result, result.assertions_count, gate_score
            )
        ctx_from_table = table_context or {}
        logger.info(
            "generic_validator: table_id=%s classifier=%s final_status=%s assertions_count=%s no_assertion_reason=%s",
            ctx_from_table.get("table_id", ""),
            ctx_from_table.get("classifier_type", ""),
            result.status_enum,
            result.assertions_count,
            result.context.get("no_assertion_reason") if result.context else None,
        )
        return result

    def _needs_column_check(self, heading_lower: str) -> bool:
        """Check if table needs column-based validation."""
        return heading_lower in [name.lower() for name in TABLES_NEED_COLUMN_CHECK]

    def _detect_movement_structure(
        self, df: pd.DataFrame
    ) -> Optional[Dict[str, object]]:
        """
        Scan first column for OB/CB/movement-like labels.
        Returns dict with ob_row, cb_row, movement_rows (list of row indices) or None.
        Used when movement_rollforward flag is on to detect movement/reconciliation tables.
        """
        if df is None or df.empty or len(df.columns) < 2:
            return None
        first_col = df.iloc[:, 0].astype(str).str.strip().str.lower()
        ob_terms = [
            "opening balance",
            "brought forward",
            "số đầu",
            "đầu kỳ",
            "beginning",
            "đầu năm",
        ]
        cb_terms = [
            "closing balance",
            "carried forward",
            "số cuối",
            "cuối kỳ",
            "ending",
            "cuối năm",
        ]
        movement_terms = [
            "addition",
            "additions",
            "disposal",
            "disposals",
            "depreciation",
            "acquisition",
            "transfer",
            "increase",
            "decrease",
            "phát sinh",
            "chuyển",
        ]
        ob_row: Optional[int] = None
        cb_row: Optional[int] = None
        movement_rows: List[int] = []
        for idx, val in first_col.items():
            v = (val or "").strip().lower()
            if not v:
                continue
            for t in ob_terms:
                if t in v:
                    ob_row = int(idx)
                    break
            for t in cb_terms:
                if t in v:
                    cb_row = int(idx)
                    break
            for t in movement_terms:
                if t in v:
                    movement_rows.append(int(idx))
                    break
        if ob_row is not None and cb_row is not None:
            return {
                "ob_row": ob_row,
                "cb_row": cb_row,
                "movement_rows": movement_rows,
            }
        return None

    def _validate_rollforward(
        self,
        df_numeric: pd.DataFrame,
        movement_structure: Dict[str, object],
        amount_cols: Sequence[Union[int, str]],
        marks: List[Dict[str, object]],
        issues: List[str],
    ) -> None:
        """
        Validate OB + sum(movement rows) ≈ CB per amount column (roll-forward).
        Uses compare_amounts for tolerance; appends to marks/issues on mismatch.
        """
        ob_row = movement_structure.get("ob_row")
        cb_row = movement_structure.get("cb_row")
        _raw_movement = movement_structure.get("movement_rows") or []
        movement_rows: List[int] = (
            list(_raw_movement) if isinstance(_raw_movement, (list, tuple)) else []
        )
        if ob_row is None or cb_row is None or df_numeric.empty:
            return
        for col in amount_cols:
            try:
                ob_val = pd.to_numeric(df_numeric.loc[ob_row, col], errors="coerce")
                cb_val = pd.to_numeric(df_numeric.loc[cb_row, col], errors="coerce")
            except (KeyError, TypeError):
                continue
            if pd.isna(ob_val) or pd.isna(cb_val):
                continue
            movement_sum = 0.0
            for r in movement_rows:
                try:
                    v = pd.to_numeric(df_numeric.loc[r, col], errors="coerce")
                    movement_sum += v if not pd.isna(v) else 0.0
                except (KeyError, TypeError):
                    continue
            expected = float(ob_val) + movement_sum
            actual = float(cb_val)
            is_ok, abs_delta, rel_delta, tol_used = compare_amounts(expected, actual)
            if not is_ok:
                if isinstance(col, int):
                    col_idx = col
                else:
                    col_idx = (
                        df_numeric.columns.get_loc(col)
                        if col in df_numeric.columns
                        else 0
                    )
                marks.append({"row": cb_row, "col": col_idx, "message": "roll-forward"})
                issues.append(
                    f"Roll-forward (OB + movements ≈ CB) - Cột {col}: "
                    f"Kỳ vọng={expected:,.2f}, Thực tế={actual:,.2f}, Sai lệch={abs_delta:,.2f} ({tol_used})"
                )
        return

    def _infer_total_column(
        self,
        df_numeric: pd.DataFrame,
        anchor_rows: List[int],
    ) -> Optional[int]:
        """
        Ticket-2: Infer which column is the "Total" column by checking if its
        value ≈ sum of all other numeric columns across anchor rows.
        Returns column index or None.
        """
        if df_numeric.empty or len(df_numeric.columns) < 3:
            return None
        df_calc = df_numeric.apply(pd.to_numeric, errors="coerce")
        valid_anchors = [r for r in anchor_rows if 0 <= r < len(df_calc)]
        if not valid_anchors:
            return None
        best_col: Optional[int] = None
        best_matches = 0
        for col_idx in range(len(df_calc.columns)):
            matches = 0
            for r in valid_anchors:
                row_vals = df_calc.iloc[r]
                candidate_val = row_vals.iloc[col_idx]
                if pd.isna(candidate_val):
                    continue
                other_sum = 0.0
                other_count = 0
                for j in range(len(row_vals)):
                    if j == col_idx:
                        continue
                    v = row_vals.iloc[j]
                    if not pd.isna(v):
                        other_sum += v
                        other_count += 1
                if other_count < 2:
                    continue
                is_ok, _, _, _ = compare_amounts(other_sum, float(candidate_val))
                if is_ok:
                    matches += 1
            if matches > best_matches:
                best_matches = matches
                best_col = col_idx
        # Require at least 2 anchor rows to match
        if best_matches >= 2:
            return best_col
        return None

    def _validate_fixed_assets(
        self, df: pd.DataFrame, df_numeric: pd.DataFrame, heading_lower: str
    ) -> ValidationResult:
        """Validate fixed assets table with cost, accumulated depreciation, and NBV."""
        # Ensure numeric arithmetic is performed on numeric-only view (drop/NaN-out text columns).
        df_calc = df_numeric.apply(pd.to_numeric, errors="coerce")
        # Find rows containing keywords (flexible for CJCGV/CP Vietnam and variants)
        cost_keywords = [
            "cost",
            "giá vốn",
            "giá trị gốc",
            "nguyên giá",
            "original cost",
            "gross",
        ]
        AD_keywords = [
            "accumulated depreciation",
            "accumulated amortisation",
            "accumulated",
            "depreciation",
            "amortisation",
            "khấu hao lũy kế",
            "hao mòn lũy kế",
            "ad",
        ]
        NBV_keywords = [
            "net book value",
            "net book",
            "book value",
            "giá trị còn lại",
            "nbv",
            "carrying amount",
            "carrying value",
        ]

        cost_start_row_idx = None
        AD_start_row_idx = None
        NBV_start_row_idx = None

        for i, row in df.iterrows():
            row_text = " ".join(str(cell).lower() for cell in row)
            if any(keyword.lower() in row_text for keyword in cost_keywords):
                cost_start_row_idx = i
            if any(keyword.lower() in row_text for keyword in AD_keywords):
                AD_start_row_idx = i
            if any(keyword.lower() in row_text for keyword in NBV_keywords):
                NBV_start_row_idx = i

        if (
            cost_start_row_idx is None
            or AD_start_row_idx is None
            or NBV_start_row_idx is None
        ):
            return ValidationResult(
                status="WARN: Fixed assets - không tìm thấy đầy đủ các dòng Cost, AD, NBV",
                marks=[],
                cross_ref_marks=[],
            )

        # Calculate sums and totals
        # SCRUM-5/6: Bounds checking before iloc access
        if (
            cost_start_row_idx is None
            or AD_start_row_idx is None
            or NBV_start_row_idx is None
            or AD_start_row_idx - 1 < 0
            or AD_start_row_idx - 1 >= len(df_numeric)
            or NBV_start_row_idx - 1 < 0
            or NBV_start_row_idx - 1 >= len(df_numeric)
            or cost_start_row_idx + 1 >= len(df_numeric)
            or AD_start_row_idx + 1 >= len(df_numeric)
            or NBV_start_row_idx + 1 >= len(df_numeric)
            or NBV_start_row_idx + 2 >= len(df_numeric)
        ):
            return ValidationResult(
                status="WARN: Fixed assets - indices out of bounds for table structure",
                marks=[],
                cross_ref_marks=[],
            )

        cost_detail_sum = df_calc.iloc[cost_start_row_idx : AD_start_row_idx - 2].sum(
            skipna=True
        )
        cost_total_row = df_calc.iloc[AD_start_row_idx - 1]
        AD_detail_sum = df_calc.iloc[AD_start_row_idx : NBV_start_row_idx - 2].sum(
            skipna=True
        )
        AD_total_row = df_calc.iloc[NBV_start_row_idx - 1]
        OB_detail_cal = (
            df_calc.iloc[cost_start_row_idx + 1] - df_calc.iloc[AD_start_row_idx + 1]
        )
        CB_detail_cal = cost_total_row - AD_total_row
        OB_NBV_total_row = df_calc.iloc[NBV_start_row_idx + 1]
        CB_NBV_total_row = df_calc.iloc[NBV_start_row_idx + 2]

        issues: List[str] = []
        marks: List[Dict] = []
        cross_ref_marks: List[Dict] = []

        # Validate cost totals
        for col in range(len(df.columns)):
            if not pd.isna(cost_total_row.iloc[col]) and not pd.isna(
                cost_detail_sum.iloc[col]
            ):
                diff = cost_detail_sum.iloc[col] - cost_total_row.iloc[col]
                is_ok = abs(round(diff)) == 0
                comment = f"DÒNG TỔNG (GV) - Cột {col + 1}: Tính lại={cost_detail_sum.iloc[col]:,.2f}, Trên bảng={cost_total_row.iloc[col]:,.2f}, Sai lệch={diff:,.2f}"
                marks.append(
                    {
                        "row": AD_start_row_idx - 1,
                        "col": col,
                        "ok": is_ok,
                        "comment": None if is_ok else comment,
                    }
                )
                if not is_ok:
                    issues.append(comment)

        # Validate accumulated depreciation totals
        for col in range(len(df.columns)):
            if not pd.isna(AD_total_row.iloc[col]) and not pd.isna(
                AD_detail_sum.iloc[col]
            ):
                diff = AD_detail_sum.iloc[col] - AD_total_row.iloc[col]
                is_ok = abs(round(diff)) == 0
                comment = f"DÒNG TỔNG (AD) - Cột {col + 1}: Tính lại={AD_detail_sum.iloc[col]:,.2f}, Trên bảng={AD_total_row.iloc[col]:,.2f}, Sai lệch={diff:,.2f}"
                marks.append(
                    {
                        "row": NBV_start_row_idx - 1,
                        "col": col,
                        "ok": is_ok,
                        "comment": None if is_ok else comment,
                    }
                )
                if not is_ok:
                    issues.append(comment)

        # Validate NBV (Opening Balance and Closing Balance)
        for col in range(len(df.columns)):
            if (
                not pd.isna(OB_NBV_total_row.iloc[col])
                and not pd.isna(CB_NBV_total_row.iloc[col])
                and not pd.isna(OB_detail_cal.iloc[col])
                and not pd.isna(CB_detail_cal.iloc[col])
            ):
                diffOB = OB_detail_cal.iloc[col] - OB_NBV_total_row.iloc[col]
                diffCB = CB_detail_cal.iloc[col] - CB_NBV_total_row.iloc[col]
                is_okOB = abs(round(diffOB)) == 0
                is_okCB = abs(round(diffCB)) == 0

                commentOB = f"DÒNG TỔNG (OB NBV) - Cột {col + 1}: Tính lại={OB_detail_cal.iloc[col]:,.2f}, Trên bảng={OB_NBV_total_row.iloc[col]:,.2f}, Sai lệch={diffOB:,.2f}"
                marks.append(
                    {
                        "row": NBV_start_row_idx + 1,
                        "col": col,
                        "ok": is_okOB,
                        "comment": None if is_okOB else commentOB,
                    }
                )
                if not is_okOB:
                    issues.append(commentOB)

                commentCB = f"DÒNG TỔNG (CB NBV) - Cột {col + 1}: Tính lại={CB_detail_cal.iloc[col]:,.2f}, Trên bảng={CB_NBV_total_row.iloc[col]:,.2f}, Sai lệch={diffCB:,.2f}"
                marks.append(
                    {
                        "row": NBV_start_row_idx + 2,
                        "col": col,
                        "ok": is_okCB,
                        "comment": None if is_okCB else commentCB,
                    }
                )
                if not is_okCB:
                    issues.append(commentCB)

        # SCRUM-12: Cross-check NBV with BSPL using year alignment
        # Prefer numeric Total/Tổng column: Priority 1 exact/standalone, Priority 2 partial match
        roles, _, _ = infer_column_roles(df)
        total_col = None
        for col in df.columns:
            col_lower = str(col).lower().strip()
            if (
                col_lower in ("total", "tổng")
                or col_lower.endswith(" total")
                or col_lower.endswith(" tổng")
            ):
                if col in roles and roles[col] == ROLE_NUMERIC:
                    total_col = col
                    break
        if not total_col:
            for col in df.columns:
                if re.search(r"\btotal\b|\btổng\b", str(col).lower().strip()):
                    if col in roles and roles[col] == ROLE_NUMERIC:
                        total_col = col
                        break
        if total_col:
            detected_cur_col = total_col
            detected_prior_col = total_col
        else:
            detected_cur_col, detected_prior_col = (
                ColumnDetector.detect_financial_columns_advanced(df)
            )

        # P0.3: When detection returns (None, None), try _infer_total_column, then feature-flagged fallback
        if not detected_cur_col and not detected_prior_col:
            # Ticket-2: Try anchor-based total column inference
            anchor_rows = []
            if AD_start_row_idx is not None and AD_start_row_idx - 1 >= 0:
                anchor_rows.append(AD_start_row_idx - 1)  # Cost closing row
            if NBV_start_row_idx is not None and NBV_start_row_idx - 1 >= 0:
                anchor_rows.append(NBV_start_row_idx - 1)  # AD closing row
            if NBV_start_row_idx is not None and NBV_start_row_idx + 2 < len(
                df_numeric
            ):
                anchor_rows.append(NBV_start_row_idx + 2)  # NBV closing row
            inferred_total_col = self._infer_total_column(df_numeric, anchor_rows)
            if inferred_total_col is not None:
                CY_col_idx = inferred_total_col
                PY_col_idx = inferred_total_col
                logger.info(
                    "Ticket-2: _infer_total_column found col_idx=%s for FA cross-check",
                    inferred_total_col,
                )
            elif (
                get_feature_flags().get("use_last_two_columns_fallback", False)
                and len(df.columns) >= 2
            ):
                CY_col_idx = len(df.columns) - 1
                PY_col_idx = len(df.columns) - 2
            else:
                return ValidationResult(
                    status="FAIL_TOOL_EXTRACT: Không có cặp cột CY/PY đủ bằng chứng số",
                    marks=marks,
                    cross_ref_marks=cross_ref_marks,
                    rule_id="NO_NUMERIC_EVIDENCE",
                    status_enum="FAIL_TOOL_EXTRACT",
                    context={"failure_reason_code": "NO_NUMERIC_EVIDENCE"},
                )
        else:
            # Detection succeeded — resolve column indices
            CY_col_idx = len(df.columns) - 1  # Default if lookup fails below
            PY_col_idx = (
                len(df.columns) - 2 if len(df.columns) >= 2 else len(df.columns) - 1
            )
            if detected_cur_col and detected_prior_col:
                try:
                    col_list = list(df.columns)
                    CY_col_idx = (
                        col_list.index(detected_cur_col)
                        if detected_cur_col in col_list
                        else len(df.columns) - 1
                    )
                    PY_col_idx = (
                        col_list.index(detected_prior_col)
                        if detected_prior_col in col_list
                        else len(df.columns) - 1
                    )
                except (ValueError, IndexError):
                    pass  # Use fallback

        account_name: Optional[str] = heading_lower
        # SCRUM-12: Bounds checking with year-aligned columns
        CY_bal = 0.0
        PY_bal = 0.0
        if (
            NBV_start_row_idx + 2 < len(df_numeric)
            and CY_col_idx >= 0
            and CY_col_idx < len(df_numeric.columns)
        ) and not pd.isna(df_numeric.iloc[NBV_start_row_idx + 2, CY_col_idx]):
            CY_bal = df_numeric.iloc[NBV_start_row_idx + 2, CY_col_idx]
        if (
            NBV_start_row_idx + 1 < len(df_numeric)
            and PY_col_idx >= 0
            and PY_col_idx < len(df_numeric.columns)
        ) and not pd.isna(df_numeric.iloc[NBV_start_row_idx + 1, PY_col_idx]):
            PY_bal = df_numeric.iloc[NBV_start_row_idx + 1, PY_col_idx]
        if account_name:
            self.cross_check_with_BSPL(
                df,
                cross_ref_marks,
                issues,
                account_name,
                CY_bal,
                PY_bal,
                NBV_start_row_idx + 2,
                CY_col_idx,
                1,
                CY_col_idx - PY_col_idx,
            )
            if self.context:
                self.context.marks.add(account_name)

        # SCRUM-12: Cross-check Cost with BSPL accounts using year alignment
        # Use same year-aligned columns detected above
        CY_bal = 0.0
        PY_bal = 0.0
        if (
            AD_start_row_idx - 1 >= 0
            and AD_start_row_idx - 1 < len(df_numeric)
            and CY_col_idx >= 0
            and CY_col_idx < len(df_numeric.columns)
        ) and not pd.isna(df_numeric.iloc[AD_start_row_idx - 1, CY_col_idx]):
            CY_bal = df_numeric.iloc[AD_start_row_idx - 1, CY_col_idx]
        if (
            cost_start_row_idx + 1 < len(df_numeric)
            and PY_col_idx >= 0
            and PY_col_idx < len(df_numeric.columns)
        ) and not pd.isna(df_numeric.iloc[cost_start_row_idx + 1, PY_col_idx]):
            PY_bal = df_numeric.iloc[cost_start_row_idx + 1, PY_col_idx]

        # Map heading to account code for cost
        cost_account_name: Optional[str]
        if heading_lower == "tangible fixed assets":
            cost_account_name = "222"
        elif heading_lower == "finance lease tangible fixed assets":
            cost_account_name = "225"
        elif heading_lower == "intangible fixed assets":
            cost_account_name = "228"
        elif heading_lower == "investment property":
            cost_account_name = "231"
        else:
            cost_account_name = None

        if cost_account_name:
            gap_row = AD_start_row_idx - 1 - (cost_start_row_idx + 1)
            self.cross_check_with_BSPL(
                df,
                cross_ref_marks,
                issues,
                cost_account_name,
                CY_bal,
                PY_bal,
                AD_start_row_idx - 1,
                CY_col_idx,
                gap_row,
                CY_col_idx - PY_col_idx,
            )
            if self.context:
                self.context.marks.add(cost_account_name)

        # SCRUM-12: Cross-check Accumulated Depreciation with BSPL accounts using year alignment
        # Use same year-aligned columns detected above
        CY_bal = 0.0
        PY_bal = 0.0
        if (
            NBV_start_row_idx - 1 >= 0
            and NBV_start_row_idx - 1 < len(df_numeric)
            and CY_col_idx >= 0
            and CY_col_idx < len(df_numeric.columns)
        ) and not pd.isna(df_numeric.iloc[NBV_start_row_idx - 1, CY_col_idx]):
            CY_bal = df_numeric.iloc[NBV_start_row_idx - 1, CY_col_idx] * -1
        if (
            AD_start_row_idx + 1 < len(df_numeric)
            and PY_col_idx >= 0
            and PY_col_idx < len(df_numeric.columns)
        ) and not pd.isna(df_numeric.iloc[AD_start_row_idx + 1, PY_col_idx]):
            PY_bal = df_numeric.iloc[AD_start_row_idx + 1, PY_col_idx] * -1

        # Map heading to account code for accumulated depreciation
        ad_account_name: Optional[str]
        if heading_lower == "tangible fixed assets":
            ad_account_name = "223"
        elif heading_lower == "finance lease tangible fixed assets":
            ad_account_name = "226"
        elif heading_lower == "intangible fixed assets":
            ad_account_name = "229"
        elif heading_lower == "investment property":
            ad_account_name = "232"
        else:
            ad_account_name = None

        if ad_account_name:
            gap_row = NBV_start_row_idx - 1 - (AD_start_row_idx + 1)
            self.cross_check_with_BSPL(
                df,
                cross_ref_marks,
                issues,
                ad_account_name,
                CY_bal,
                PY_bal,
                NBV_start_row_idx - 1,
                CY_col_idx,
                gap_row,
                CY_col_idx - PY_col_idx,
            )
            if self.context:
                self.context.marks.add(ad_account_name)

        # Generate status
        if not issues:
            status = "PASS: Fixed assets - kiểm tra công thức: KHỚP (0 sai lệch)"
        else:
            preview = "; ".join(issues[:10])
            more = f" ... (+{len(issues) - 10} dòng)" if len(issues) > 10 else ""
            status = f"FAIL: Fixed assets - kiểm tra công thức: {len(issues)} sai lệch. {preview}{more}"

        return ValidationResult(
            status=status, marks=marks, cross_ref_marks=cross_ref_marks
        )

    def _validate_column_totals(
        self,
        df_numeric: pd.DataFrame,
        total_row_idx: int,
        last_col_idx: int,
        marks: List[Dict],
        issues: List[str],
        code_col: Optional[str] = None,
        code_cols: Optional[Sequence[str]] = None,
    ) -> None:
        """
        SCRUM-12: Validate column totals with guards.
        Only check when total column is identified and has sufficient numeric cells.
        """
        # Guard: Check if total column index is valid
        if last_col_idx < 0 or last_col_idx >= len(df_numeric.columns):
            return

        # Guard: Check if total_row_idx is valid
        if total_row_idx < 0 or total_row_idx >= len(df_numeric):
            return

        # Guard: Check if there are sufficient numeric cells in detail region
        detail_region = df_numeric.iloc[: total_row_idx + 1, :last_col_idx]
        numeric_cell_count = detail_region.notna().sum().sum()

        if numeric_cell_count < 3:  # Need at least 3 numeric cells for meaningful check
            return

        # Validate column totals
        for i in range(total_row_idx + 1):
            # SCRUM-5/6: Bounds checking before iloc access
            if i >= len(df_numeric):
                continue

            row = df_numeric.iloc[i]

            # Guard: Check if row has sufficient numeric values
            detail_values = row.iloc[:last_col_idx]
            if detail_values.notna().sum() < 2:  # Need at least 2 values to sum
                continue

            drop_cols = [df_numeric.columns[last_col_idx]]
            exclude = list(code_cols) if code_cols else ([code_col] if code_col else [])
            for c in exclude:
                if c in row.index and c not in drop_cols:
                    drop_cols.append(c)
            row_sum = row.drop(labels=drop_cols, errors="ignore").sum(skipna=True)

            # Guard: Check bounds for last_col_idx
            if last_col_idx >= len(row):
                continue

            col_total_val = row.iloc[last_col_idx]

            if not pd.isna(col_total_val) and not pd.isna(row_sum):
                diff = row_sum - float(col_total_val)
                is_ok, _, _, _ = compare_amounts(row_sum, float(col_total_val))

                comment = (
                    f"CỘT TỔNG - Dòng {i + 1}: Tính lại={row_sum:,.2f}, "
                    f"Trên bảng={col_total_val:,.2f}, Sai lệch={diff:,.2f}"
                )

                marks.append(
                    {
                        "row": i,
                        "col": last_col_idx,
                        "ok": is_ok,
                        "comment": None if is_ok else comment,
                    }
                )

                if not is_ok:
                    issues.append(comment)

    # R4: Lexicon for netting "Less" row detection (normalized tokens / phrases).
    _NETTING_LESS_LEXICON = frozenset(
        {
            "less",
            "deduct",
            "deduction",
            "deductions",
            "contra revenue",
            "returns",
            "discounts",
            "allowances",
            "trừ",
            "giảm trừ",
        }
    )
    _NETTING_NET_EXCLUDE = frozenset({"book value"})

    def _normalize_row_text(self, row: pd.Series) -> str:
        """Lowercase, strip punctuation, collapse whitespace for netting detection."""
        raw = " ".join(str(cell).strip() for cell in row if pd.notna(cell))
        no_punct = re.sub(r"[^\w\s]", " ", raw.lower())
        return re.sub(r"\s+", " ", no_punct).strip()

    def _detect_netting_structure(self, df: pd.DataFrame) -> Optional[Dict[str, int]]:
        """
        Detect a Total/Less/Net structure with adjacency constraint.

        Uses normalized row text, expanded lexicon, and adjacency 5 then 10-15.
        Returns:
            Dict with keys {'total','less','net'} mapping to row indices, or None.
        """
        total_rows: List[int] = []
        less_rows: List[int] = []
        net_rows: List[int] = []

        for idx, row in df.iterrows():
            row_text = self._normalize_row_text(row)
            if not row_text:
                continue
            has_less = any(term in row_text for term in self._NETTING_LESS_LEXICON)
            has_net = "net" in row_text and not any(
                ex in row_text for ex in self._NETTING_NET_EXCLUDE
            )
            has_total = "total" in row_text
            if has_total and not has_less and not has_net:
                total_rows.append(idx)
            elif has_less:
                less_rows.append(idx)
            elif has_net:
                net_rows.append(idx)

        if not (total_rows and less_rows and net_rows):
            return None

        def _within(
            t_rows: List[int], l_rows: List[int], n_rows: List[int], max_dist: int
        ) -> Optional[Dict[str, int]]:
            for total_idx in t_rows:
                for less_idx in l_rows:
                    for net_idx in n_rows:
                        if (
                            max(total_idx, less_idx, net_idx)
                            - min(total_idx, less_idx, net_idx)
                            <= max_dist
                        ):
                            return {
                                "total": total_idx,
                                "less": less_idx,
                                "net": net_idx,
                            }
            return None

        # Prefer strict adjacency then relaxed; configurable via feature flags
        flags = get_feature_flags()
        max_strict = flags.get("netting_adjacency_strict", 5)
        max_relaxed = flags.get("netting_adjacency_relaxed", 25)
        return _within(total_rows, less_rows, net_rows, max_strict) or _within(
            total_rows, less_rows, net_rows, max_relaxed
        )

    def _validate_row_totals(
        self,
        df: pd.DataFrame,
        df_numeric: pd.DataFrame,
        total_row_idx: Optional[int],  # Make optional as it might not be found
        code_col: Optional[str],  # Add code_col parameter (backward compat)
        heading_lower: str,
        marks: List[Dict],
        issues: List[str],
        cross_ref_marks: List[Dict],
        code_cols: Optional[Sequence[str]] = None,
        amount_cols: Optional[Sequence[str]] = None,
    ) -> None:
        """Validate row totals and cross-references with block-sum validation."""
        code_cols_set = (
            set(code_cols) if code_cols else (set([code_col]) if code_col else set())
        )
        amount_cols_set = set(amount_cols) if amount_cols else set()

        # Skip column total validation for statements (income, cash flow, equity)
        # They have multiple subtotals and use formula-based validation instead (Issue 3.2)
        is_statement = any(
            keyword in heading_lower
            for keyword in [
                "statement of income",
                "income statement",
                "cash flow",
                "changes in owners' equity",
                "changes in equity",
                "statement of comprehensive income",
            ]
        )
        if is_statement:
            logger.debug(
                "Skipping column total validation for statement table: %s",
                heading_lower,
            )
            return

        # If amount columns were detected, restrict checks to those columns only.
        def _should_check_col(col_name: str) -> bool:
            if col_name in code_cols_set:
                return False
            if amount_cols_set:
                return col_name in amount_cols_set
            return True

        # Heuristic to downgrade subtotal double-counting to INFO in oversum cases.
        has_subtotal = any(
            "subtotal" in " ".join(str(cell).lower() for cell in df.iloc[i])
            for i in range(0, len(df))
        )
        # Default block start (row index before first detail row).
        # If the table begins with one or more empty rows, use the last leading-empty row
        # as the block boundary. Use numeric-aware check: treat as data row only if
        # >= 50% of amount columns have data, or >= 2 numeric values (excluding code).
        amount_col_list = [c for c in df.columns if c not in code_cols_set]
        n_amount = len(amount_col_list) if amount_col_list else 0

        start_idx = -1
        for i in range(0, min(5, len(df))):
            row_numeric = df_numeric.iloc[i]
            numeric_count = 0
            for col_idx, col_name in enumerate(df.columns):
                if col_name in code_cols_set:
                    continue
                if not pd.isna(row_numeric.iloc[col_idx]):
                    numeric_count += 1
            # Data row if >= 50% of amount columns have data, or >= 2 numeric values
            has_numeric = (
                n_amount > 0 and numeric_count >= max(1, (n_amount + 1) // 2)
            ) or numeric_count >= 2
            if not has_numeric:
                start_idx = i
            else:
                break

        # P1-5: Netting validation must be structure-driven (Total/Less/Net adjacency)
        flags = get_feature_flags()
        if flags.get("strict_netting_structure", True):
            netting_structure = self._detect_netting_structure(df)
            if not netting_structure:
                logger.debug(
                    "Netting validation skipped: no valid Total/Less/Net structure detected"
                )
            else:
                total_row_idx_net = netting_structure["total"]
                less_row_idx = netting_structure["less"]
                net_row_idx = netting_structure["net"]

                valid_netting_cols = 0
                netting_diffs = []

                # Ticket 7: Netting Anchor Fallback
                less_row_text = str(df.iloc[less_row_idx].values).lower()
                has_netting_anchor = any(
                    k in less_row_text for k in ["dự phòng", "allowance", "provision"]
                )

                for col_idx, col_name in enumerate(df.columns):
                    if col_name in code_cols_set:
                        continue
                    total_val = df_numeric.iloc[total_row_idx_net, col_idx]
                    less_val = df_numeric.iloc[less_row_idx, col_idx]
                    net_val = df_numeric.iloc[net_row_idx, col_idx]
                    if pd.isna(total_val) or pd.isna(less_val) or pd.isna(net_val):
                        continue

                    # Ticket 7: Explicit Sign Requirement (B must be negative)
                    # We check if less_val is negative. If it's positive, we check if the anchor exists.
                    if less_val > 0 and not has_netting_anchor:
                        continue  # Skip this column as it violates sign requirement

                    expected_net = (
                        total_val + less_val if less_val < 0 else total_val - less_val
                    )
                    diff = expected_net - net_val
                    netting_diffs.append((col_idx, diff, total_val, less_val, net_val))
                    if abs(round(diff)) == 0:
                        valid_netting_cols += 1

                # Ticket 7: Cross-Column Consistency
                # A + B = C must hold on >= 2 numeric columns, OR strictly 0 diff for 1 numeric column
                is_netting_valid_overall = False
                if len(netting_diffs) >= 2 and valid_netting_cols >= 2:
                    is_netting_valid_overall = True
                elif len(netting_diffs) == 1 and valid_netting_cols == 1:
                    is_netting_valid_overall = True

                if is_netting_valid_overall:
                    for col_idx, diff, total_val, less_val, net_val in netting_diffs:
                        is_ok = abs(round(diff)) == 0
                        comment = (
                            f"Netting validation - Cột {col_idx + 1}: "
                            f"Total = {total_val:,.2f}, Less = {less_val:,.2f}, "
                            f"Expected Net = {(total_val + less_val if less_val < 0 else total_val - less_val):,.2f}, Actual Net = {net_val:,.2f}, "
                            f"Sai lệch = {diff:,.2f}"
                        )
                        marks.append(
                            {
                                "row": net_row_idx,
                                "col": col_idx,
                                "ok": is_ok,
                                "comment": None if is_ok else comment,
                                "rule_id": "NETTING_VALIDATION",
                            }
                        )
                        if not is_ok:
                            issues.append(comment)
                    # R4: Gate grand-total path when netting was used to avoid double-validate.
                    return
                else:
                    logger.debug(
                        "Netting structure rejected due to cross-column consistency or sign requirement failure."
                    )

        row_types = None

        def find_block_sum(start_idx):
            """Find sum of values in a block using semantic row boundaries (RowClassifier)."""
            nonlocal row_types
            if row_types is None:
                from ...utils.row_classifier import RowClassifier

                row_types = RowClassifier.classify_rows(df)
            from ...utils.row_classifier import RowType

            sum_vals = [0.0] * len(df.columns)
            count = 0
            i = start_idx + 1

            while i < len(df):
                rt = row_types[i]

                # Check for formula patterns to void block calculation
                row_str = " ".join(str(c) for c in df.iloc[i]).lower()
                if any(re.search(pat, row_str) for pat in FORMULA_KEYWORDS):
                    logger.debug(
                        "Block summation voided at row %d due to formula keyword.", i
                    )
                    return sum_vals, 0, i - 1

                if rt in (RowType.SUBTOTAL, RowType.TOTAL):
                    # Total is on this exact row, return i-1 so caller's `end1 + 1` points here.
                    return sum_vals, count, i - 1

                if rt != RowType.DATA:
                    # Boundary reached (EMPTY, SECTION_TITLE, FOOTER).
                    # Returns i so caller's `end1 + 1` looks at the row after this boundary.
                    return sum_vals, count, i

                row_numeric = df_numeric.iloc[i]
                has_numeric = False
                for col_idx, col_name in enumerate(df.columns):
                    if not _should_check_col(str(col_name)):
                        continue
                    val = row_numeric.iloc[col_idx]
                    if not pd.isna(val) and not is_year_like_value(val):
                        sum_vals[col_idx] += float(val)
                        has_numeric = True

                if not has_numeric:
                    # Fallback boundary if RowClassifier is overly optimistic about DATA
                    return sum_vals, count, i

                count += 1
                i += 1

            return sum_vals, count, i

        def compare_sum_with_total(sum_vals, total_row, end_row, block_start_idx=None):
            """Compare calculated sum with total row."""
            for col_idx, col_name in enumerate(df.columns):
                if not _should_check_col(str(col_name)):
                    continue
                total_val = total_row.iloc[col_idx]
                if not pd.isna(total_val):
                    # Pattern C diagnostic: log when sum_detail=0 but total_on_table large (gated by flag)
                    if (
                        get_feature_flags().get("enable_pattern_c_diagnostics", True)
                        and sum_vals[col_idx] == 0
                        and abs(total_val) > 1.0
                    ):
                        sample = []
                        if (
                            block_start_idx is not None
                            and end_row is not None
                            and col_idx < df_numeric.shape[1]
                        ):
                            end_excl = min(end_row + 2, len(df_numeric))
                            sample = df_numeric.iloc[
                                block_start_idx + 1 : end_excl, col_idx
                            ].tolist()
                        logger.debug(
                            "Pattern C diagnostic - Col %s: sum_detail=0, total_on_table=%s, "
                            "start_idx=%s, block_end=%s, code_cols=%s, df_numeric sample=%s",
                            col_idx + 1,
                            total_val,
                            block_start_idx,
                            end_row,
                            list(code_cols_set),
                            sample,
                        )
                    diff = sum_vals[col_idx] - total_val
                    is_ok = abs(round(diff)) == 0
                    # P4: When detail sum is 0 but total is non-zero, treat as INFO (year col or no detail rows).
                    if sum_vals[col_idx] == 0 and abs(total_val) > 0:
                        is_ok = True
                        comment = (
                            f"INFO: Cột {col_idx + 1}: Tổng chi tiết = 0 "
                            "(có thể cột năm hoặc không có dòng chi tiết)"
                        )
                    elif (
                        has_subtotal
                        and total_val != 0
                        and abs(sum_vals[col_idx]) > 1.8 * abs(total_val)
                    ):
                        # Oversum likely due to subtotal rows included in detail sum.
                        is_ok = True
                        comment = (
                            f"INFO: Cột {col_idx + 1}: Có subtotal → oversum "
                            f"(Tính lại={sum_vals[col_idx]:,.2f}, Trên bảng={total_val:,.2f}, Sai lệch={diff:,.0f})"
                        )
                    else:
                        comment = (
                            f"Cột {col_idx + 1}: Tổng chi tiết = {sum_vals[col_idx]:,.2f}, "
                            f"Tổng trên bảng = {total_val:,.2f}, Sai lệch = {diff:,.0f}"
                        )
                    marks.append(
                        {
                            "row": end_row + 1,
                            "col": col_idx,
                            "ok": is_ok,
                            "comment": None if is_ok else comment,
                        }
                    )
                    # Only treat real mismatches as issues; INFO diagnostics should not
                    # escalate the table status to FAIL/WARN.
                    if not is_ok:
                        issues.append(comment)

        # A1/A2: Prefer direct "detail-sum vs total-row" when total_row_idx is known.
        if (
            total_row_idx is not None
            and total_row_idx >= 0
            and total_row_idx < len(df_numeric)
        ):
            has_blank_in_detail = any(
                all(str(cell).strip() == "" for cell in df.iloc[i])
                for i in range(0, total_row_idx)
            )

            # Use RowClassifier to properly identify intermediate totals
            from ...utils.row_classifier import RowClassifier, RowType

            rt_list = RowClassifier.classify_rows(df)
            has_subtotal_in_detail = any(
                rt_list[i] in (RowType.SUBTOTAL, RowType.TOTAL)
                for i in range(0, total_row_idx)
            )

            # Only use the direct path for simple additive tables (no blanks/subtotals).
            if not has_blank_in_detail and not has_subtotal_in_detail:
                total_row = df_numeric.iloc[total_row_idx]
                sum_vals = [0.0] * len(df.columns)
                detail_rows = 0
                for i in range(0, total_row_idx):
                    if i >= len(df_numeric):
                        break
                    row = df.iloc[i]
                    if all(str(cell).strip() == "" for cell in row):
                        continue
                    for col_idx, col_name in enumerate(df.columns):
                        if not _should_check_col(str(col_name)):
                            continue
                        v = df_numeric.iloc[i, col_idx]
                        if not pd.isna(v) and not is_year_like_value(v):
                            sum_vals[col_idx] += float(v)
                    detail_rows += 1
                if detail_rows >= 1:
                    compare_sum_with_total(
                        sum_vals, total_row, total_row_idx - 1, block_start_idx=0
                    )
                return

        # SCRUM-12: Guard - Only validate if total_row_idx is valid and we have sufficient data
        if (
            total_row_idx is None
            or total_row_idx < 0
            or total_row_idx >= len(df_numeric)
        ):
            return

        # Find first block sum
        sum1, count1, end1 = find_block_sum(start_idx)

        # SCRUM-12: Guard - Only compare if we have sufficient detail rows (count1 > 1) and valid indices
        if count1 > 1 and end1 < len(df) - 1 and end1 + 1 < len(df_numeric):
            # Guard: Check if we have sufficient numeric cells in detail region
            detail_numeric_count = sum(
                1
                for i in range(start_idx + 1, end1 + 1)
                if i < len(df_numeric)
                and any(
                    not pd.isna(df_numeric.iloc[i, col])
                    for col in range(len(df.columns))
                )
            )

            if (
                detail_numeric_count >= 2
            ):  # Need at least 2 detail rows with numeric values
                total1_row = df_numeric.iloc[end1 + 1]
                compare_sum_with_total(
                    sum1, total1_row, end1, block_start_idx=start_idx
                )
        # Determine start for second block
        start_idx = end1 - 1 if count1 == 1 else end1 + 1

        # Find second block if total_row_idx is after first block
        if total_row_idx > start_idx + 1:
            total2 = [0.0] * len(df.columns)
            sum2, count2, end2 = find_block_sum(start_idx)
            # SCRUM-5/6: Bounds checking before iloc access
            if count2 > 1 and end2 < len(df) - 1 and end2 + 1 < len(df_numeric):
                total2_row = df_numeric.iloc[end2 + 1]
                compare_sum_with_total(
                    sum2, total2_row, end2, block_start_idx=start_idx
                )

                # Handle special case for "revenue from" with negative values
                if "revenue from" in heading_lower:
                    total2_row_num = pd.to_numeric(total2_row, errors="coerce")
                    if total2_row_num.dropna().gt(0).all():
                        for col in range(len(df.columns)):
                            total2[col] = -sum2[col]
                    else:
                        total2 = sum2
                else:
                    total2 = sum2
            else:
                total2 = sum2

            # P1-4: Removed "last row = grand total" heuristic to avoid meaningless FAILs.

            # Handle cross-checks based on form types
            if heading_lower in CROSS_CHECK_TABLES_FORM_1:
                self._handle_cross_check_form_1(
                    df, df_numeric, heading_lower, cross_ref_marks, issues
                )
            elif heading_lower in CROSS_CHECK_TABLES_FORM_2:
                self._handle_cross_check_form_2(
                    df, df_numeric, heading_lower, end1, end2, cross_ref_marks, issues
                )
        else:
            # Single block case
            if heading_lower not in CROSS_CHECK_TABLES_FORM_3:
                from ...utils.column_detector import ColumnDetector

                # Prioritize "Total" column for BSPL comparison (Issue 3.1): exact first, then partial
                roles, _, _ = infer_column_roles(df)
                total_col = None
                for col in df.columns:
                    col_lower = str(col).lower().strip()
                    if (
                        col_lower in ("total", "tổng")
                        or col_lower.endswith(" total")
                        or col_lower.endswith(" tổng")
                    ):
                        if col in roles and roles[col] == ROLE_NUMERIC:
                            total_col = col
                            break
                if not total_col:
                    for col in df.columns:
                        if re.search(r"\btotal\b|\btổng\b", str(col).lower().strip()):
                            if col in roles and roles[col] == ROLE_NUMERIC:
                                total_col = col
                                break
                if total_col:
                    detected_cur_col = total_col
                    detected_prior_col = total_col
                else:
                    detected_cur_col, detected_prior_col = (
                        ColumnDetector.detect_financial_columns_advanced(df)
                    )

                CY_col_idx = len(df.columns) - 2  # Fallback
                PY_col_idx = len(df.columns) - 1  # Fallback

                if detected_cur_col and detected_prior_col:
                    try:
                        col_list = list(df.columns)
                        CY_col_idx = (
                            col_list.index(detected_cur_col)
                            if detected_cur_col in col_list
                            else len(df.columns) - 2
                        )
                        PY_col_idx = (
                            col_list.index(detected_prior_col)
                            if detected_prior_col in col_list
                            else len(df.columns) - 1
                        )
                    except (ValueError, IndexError):
                        pass  # Use fallback

                account_name = heading_lower
                if "accounts receivable from customers" in heading_lower:
                    account_name = "accounts receivable from customers"
                if (
                    self.context
                    and account_name
                    and account_name not in self.context.marks
                ):
                    # SCRUM-12: Bounds checking with year-aligned columns
                    CY_bal = 0.0
                    PY_bal = 0.0
                    if (
                        end1 + 1 < len(df_numeric)
                        and CY_col_idx >= 0
                        and CY_col_idx < len(df_numeric.columns)
                        and PY_col_idx >= 0
                        and PY_col_idx < len(df_numeric.columns)
                    ):
                        if not pd.isna(df_numeric.iloc[end1 + 1, CY_col_idx]):
                            CY_bal = df_numeric.iloc[end1 + 1, CY_col_idx]
                        if not pd.isna(df_numeric.iloc[end1 + 1, PY_col_idx]):
                            PY_bal = df_numeric.iloc[end1 + 1, PY_col_idx]
                    self.cross_check_with_BSPL(
                        df,
                        cross_ref_marks,
                        issues,
                        account_name,
                        CY_bal,
                        PY_bal,
                        end1 + 1,
                        CY_col_idx,
                        0,
                        CY_col_idx - PY_col_idx,
                    )
                    if self.context:
                        self.context.marks.add(account_name)
                    # Backward compat: also populate global marks
                    cross_check_marks.add(account_name)
            else:
                # FORM_3: Use search functions for special cases
                self._handle_cross_check_form_3(
                    df, df_numeric, heading_lower, end1, cross_ref_marks, issues
                )

    def _handle_cross_check_form_1(
        self,
        df: pd.DataFrame,
        df_numeric: pd.DataFrame,
        heading_lower: str,
        cross_ref_marks: List[Dict],
        issues: List[str],
    ) -> None:
        """
        SCRUM-12: Handle cross-check for FORM_1 tables (cross-ref at grand total).
        Uses year alignment to find correct CY/PY columns.
        """
        from ...utils.column_detector import ColumnDetector

        account_name = heading_lower
        if "accounts receivable from customers" in heading_lower:
            account_name = "accounts receivable from customers"
        if account_name:
            # SCRUM-12: Use ColumnDetector to find CY/PY columns by year value
            detected_cur_col, detected_prior_col = (
                ColumnDetector.detect_financial_columns_advanced(df)
            )

            CY_col_idx = len(df.columns) - 2  # Fallback
            PY_col_idx = len(df.columns) - 1  # Fallback

            if detected_cur_col and detected_prior_col:
                try:
                    col_list = list(df.columns)
                    CY_col_idx = (
                        col_list.index(detected_cur_col)
                        if detected_cur_col in col_list
                        else len(df.columns) - 2
                    )
                    PY_col_idx = (
                        col_list.index(detected_prior_col)
                        if detected_prior_col in col_list
                        else len(df.columns) - 1
                    )
                except (ValueError, IndexError):
                    pass  # Use fallback

            # SCRUM-12: Bounds checking before accessing
            CY_bal = 0.0
            PY_bal = 0.0
            final_row_idx = len(df) - 1

            if (
                final_row_idx >= 0
                and final_row_idx < len(df_numeric)
                and CY_col_idx >= 0
                and CY_col_idx < len(df_numeric.columns)
                and PY_col_idx >= 0
                and PY_col_idx < len(df_numeric.columns)
            ):
                if not pd.isna(df_numeric.iloc[final_row_idx, CY_col_idx]):
                    CY_bal = df_numeric.iloc[final_row_idx, CY_col_idx]
                if not pd.isna(df_numeric.iloc[final_row_idx, PY_col_idx]):
                    PY_bal = df_numeric.iloc[final_row_idx, PY_col_idx]

            self.cross_check_with_BSPL(
                df,
                cross_ref_marks,
                issues,
                account_name,
                CY_bal,
                PY_bal,
                final_row_idx,
                CY_col_idx,
                0,
                CY_col_idx - PY_col_idx,
            )
            if self.context:
                self.context.marks.add(account_name)

    def _handle_cross_check_form_2(
        self,
        df: pd.DataFrame,
        df_numeric: pd.DataFrame,
        heading_lower: str,
        end1: int,
        end2: int,
        cross_ref_marks: List[Dict],
        issues: List[str],
    ) -> None:
        """
        SCRUM-12: Handle cross-check for FORM_2 tables (cross-ref at both subtotal and grand total).
        Uses year alignment to find correct CY/PY columns.
        """
        from ...utils.column_detector import ColumnDetector

        # SCRUM-12: Use ColumnDetector to find CY/PY columns by year value
        detected_cur_col, detected_prior_col = (
            ColumnDetector.detect_financial_columns_advanced(df)
        )

        CY_col_idx = len(df.columns) - 2  # Fallback
        PY_col_idx = len(df.columns) - 1  # Fallback

        if detected_cur_col and detected_prior_col:
            try:
                col_list = list(df.columns)
                CY_col_idx = (
                    col_list.index(detected_cur_col)
                    if detected_cur_col in col_list
                    else len(df.columns) - 2
                )
                PY_col_idx = (
                    col_list.index(detected_prior_col)
                    if detected_prior_col in col_list
                    else len(df.columns) - 1
                )
            except (ValueError, IndexError):
                pass  # Use fallback

        # Cross-check at first subtotal
        # Map long heading variants to canonical cache keys (tests rely on these).
        account_name = heading_lower
        if "revenue from sales of goods" in heading_lower:
            account_name = "revenue from sales of goods"
        if account_name:
            # SCRUM-12: Bounds checking with year-aligned columns
            CY_bal = 0.0
            PY_bal = 0.0
            if (
                end1 + 1 < len(df_numeric)
                and CY_col_idx >= 0
                and CY_col_idx < len(df_numeric.columns)
                and PY_col_idx >= 0
                and PY_col_idx < len(df_numeric.columns)
            ):
                if not pd.isna(df_numeric.iloc[end1 + 1, CY_col_idx]):
                    CY_bal = df_numeric.iloc[end1 + 1, CY_col_idx]
                if not pd.isna(df_numeric.iloc[end1 + 1, PY_col_idx]):
                    PY_bal = df_numeric.iloc[end1 + 1, PY_col_idx]
            self.cross_check_with_BSPL(
                df,
                cross_ref_marks,
                issues,
                account_name,
                CY_bal,
                PY_bal,
                end1 + 1,
                CY_col_idx,
                0,
                CY_col_idx - PY_col_idx,
            )
            if self.context:
                self.context.marks.add(account_name)

        # Cross-check "revenue deductions"
        account_name = "revenue deductions"
        if account_name:
            # SCRUM-12: Bounds checking with year-aligned columns
            CY_bal = 0.0
            PY_bal = 0.0
            if (
                end2 + 1 < len(df_numeric)
                and CY_col_idx >= 0
                and CY_col_idx < len(df_numeric.columns)
                and PY_col_idx >= 0
                and PY_col_idx < len(df_numeric.columns)
            ):
                if not pd.isna(df_numeric.iloc[end2 + 1, CY_col_idx]):
                    CY_bal = df_numeric.iloc[end2 + 1, CY_col_idx]
                if not pd.isna(df_numeric.iloc[end2 + 1, PY_col_idx]):
                    PY_bal = df_numeric.iloc[end2 + 1, PY_col_idx]
            self.cross_check_with_BSPL(
                df,
                cross_ref_marks,
                issues,
                account_name,
                CY_bal,
                PY_bal,
                end2 + 1,
                CY_col_idx,
                0,
                CY_col_idx - PY_col_idx,
            )
            if self.context:
                self.context.marks.add(account_name)

        # Cross-check "net revenue (10 = 01 - 02)"
        account_name = "net revenue (10 = 01 - 02)"
        if account_name:
            CY_bal = (
                df_numeric.iloc[len(df) - 1, len(df.columns) - 2]
                if not pd.isna(df_numeric.iloc[len(df) - 1, len(df.columns) - 2])
                else 0
            )
            PY_bal = (
                df_numeric.iloc[len(df) - 1, len(df.columns) - 1]
                if not pd.isna(df_numeric.iloc[len(df) - 1, len(df.columns) - 1])
                else 0
            )
            self.cross_check_with_BSPL(
                df,
                cross_ref_marks,
                issues,
                account_name,
                CY_bal,
                PY_bal,
                len(df) - 1,
                len(df.columns) - 2,
                0,
                -1,
            )
            if self.context:
                self.context.marks.add(account_name)

    def _handle_cross_check_form_3(
        self,
        df: pd.DataFrame,
        df_numeric: pd.DataFrame,
        heading_lower: str,
        end1: int,
        cross_ref_marks: List[Dict],
        issues: List[str],
    ) -> None:
        """Handle cross-check for FORM_3 tables with search functions."""

        def search_col_and_cross_ref(
            key_word: str, account_name: str, total_row_xref: int
        ):
            """
            SCRUM-12: Search for keyword in columns and cross-reference with year alignment.
            Prioritizes year-based column detection over keyword search.
            """
            from ...utils.column_detector import ColumnDetector

            CY_col = 0
            PY_col = 0

            # SCRUM-12: Priority 1 - Use ColumnDetector to find CY/PY columns by year value
            if hasattr(df, "columns") and len(df.columns) > 0:
                detected_cur_col, detected_prior_col = (
                    ColumnDetector.detect_financial_columns_advanced(df)
                )

                if detected_cur_col and detected_prior_col:
                    try:
                        col_list = list(df.columns)
                        CY_col = (
                            col_list.index(detected_cur_col)
                            if detected_cur_col in col_list
                            else 0
                        )
                        PY_col = (
                            col_list.index(detected_prior_col)
                            if detected_prior_col in col_list
                            else 0
                        )
                    except (ValueError, IndexError):
                        CY_col = 0
                        PY_col = 0

            # SCRUM-12: Priority 2 - Fallback to keyword search if year detection failed
            if CY_col == 0 and PY_col == 0:
                for _j, row in df.iterrows():
                    row_text = " ".join(str(x).lower() for x in row)
                    if key_word in row_text:
                        for col in range(len(df.columns)):
                            cell_text = str(row.get(col, "")).lower()
                            if key_word in cell_text:
                                if CY_col == 0:
                                    CY_col = col
                                    PY_col = CY_col
                                else:
                                    PY_col = col
                                    break
                        break

                # Special handling for short-term borrowings/bonds
                if any(
                    term in account_name
                    for term in [
                        "short-term borrowings",
                        "short-term bonds",
                        "short-term borrowing",
                        "short-term bond",
                    ]
                ):
                    temp_col = PY_col
                    PY_col = CY_col
                    CY_col = temp_col

            # SCRUM-12: Bounds checking before accessing total_row_xref
            CY_bal = 0.0
            PY_bal = 0.0

            if (
                total_row_xref >= 0
                and total_row_xref < len(df_numeric)
                and CY_col >= 0
                and CY_col < len(df_numeric.columns)
                and PY_col >= 0
                and PY_col < len(df_numeric.columns)
            ):
                if not pd.isna(df_numeric.iloc[total_row_xref, CY_col]):
                    CY_bal = df_numeric.iloc[total_row_xref, CY_col]
                if not pd.isna(df_numeric.iloc[total_row_xref, PY_col]):
                    PY_bal = df_numeric.iloc[total_row_xref, PY_col]

            # SCRUM-12: Only cross-check if we found valid columns (even if values are 0, as 0 is valid)
            if CY_col >= 0 and PY_col >= 0:
                self.cross_check_with_BSPL(
                    df,
                    cross_ref_marks,
                    issues,
                    account_name,
                    CY_bal,
                    PY_bal,
                    total_row_xref,
                    CY_col,
                    0,
                    CY_col - PY_col,
                )
            if self.context:
                self.context.marks.add(account_name)
            # Backward compat: also populate global marks
            cross_check_marks.add(account_name)

        def search_row_and_cross_ref(account_name: str, col_xref: int):
            """Search for opening balance row and cross-reference."""
            # SCRUM-5/6: Bounds checking before iloc access
            CY_row = end1 + 1
            if CY_row >= len(df_numeric):
                return  # Cannot access row beyond DataFrame bounds

            PY_row = 0
            for j, row in df.iterrows():
                row_text = " ".join(str(x).lower() for x in row)
                if "opening balance" in row_text:
                    PY_row = j
                    break

            # SCRUM-5/6: Bounds checking before iloc access
            CY_bal = 0
            if CY_row < len(df_numeric) and col_xref < len(df_numeric.columns):
                if not pd.isna(df_numeric.iloc[CY_row, col_xref]):
                    CY_bal = df_numeric.iloc[CY_row, col_xref]

            PY_bal = 0
            if PY_row < len(df_numeric) and col_xref < len(df_numeric.columns):
                if not pd.isna(df_numeric.iloc[PY_row, col_xref]):
                    PY_bal = df_numeric.iloc[PY_row, col_xref]
            if CY_row != 0 or PY_row != 0:
                self.cross_check_with_BSPL(
                    df,
                    cross_ref_marks,
                    issues,
                    account_name,
                    CY_bal,
                    PY_bal,
                    CY_row,
                    col_xref,
                    CY_row - PY_row,
                    0,
                )
            if self.context:
                self.context.marks.add(account_name)
            # Backward compat: also populate global marks
            cross_check_marks.add(account_name)

        # Handle special cases based on heading
        if heading_lower == "bad and doubtful debts":
            account_name = "allowance for doubtful debts"
            if self.context and account_name and account_name not in self.context.marks:
                search_col_and_cross_ref("allowance", account_name, end1 + 1)

        elif heading_lower == "inventories":
            # Cross-ref costs
            account_name = "141"
            if self.context and account_name and account_name not in self.context.marks:
                search_col_and_cross_ref("cost", account_name, end1 + 1)
            # Cross-ref allowance
            account_name = "149"
            if self.context and account_name and account_name not in self.context.marks:
                search_col_and_cross_ref("allowance", account_name, end1 + 1)

        elif heading_lower in [
            "equity investments in other entity",
            "equity investments in other entities",
        ]:
            # Cross-ref costs or carrying amounts
            account_name = "investments in other entities"
            if self.context and account_name and account_name not in self.context.marks:
                search_col_and_cross_ref("cost", account_name, end1 + 1)
                search_col_and_cross_ref("carrying amounts", account_name, end1 + 1)
            # Cross-ref allowance
            account_name = "254"
            if self.context and account_name and account_name not in self.context.marks:
                search_col_and_cross_ref(
                    "allowance for diminution in value", account_name, end1 + 1
                )

        elif heading_lower == "construction in progress":
            account_name = heading_lower
            if self.context and account_name and account_name not in self.context.marks:
                search_row_and_cross_ref(account_name, 1)

        elif heading_lower == "long-term prepaid expenses":
            account_name = heading_lower
            if self.context and account_name and account_name not in self.context.marks:
                search_row_and_cross_ref(account_name, len(df.columns) - 1)

        elif "accounts payable to suppliers" in heading_lower:
            account_name = "accounts payable to suppliers"
            if self.context and account_name and account_name not in self.context.marks:
                search_col_and_cross_ref("cost", account_name, end1 + 1)

        elif "taxes" in heading_lower:
            account_name = heading_lower
            if self.context and account_name and account_name not in self.context.marks:
                # SCRUM-5/6: Bounds checking before iloc access
                CY_bal = 0
                PY_bal = 0
                if end1 + 1 < len(df_numeric) and len(df.columns) >= 1:
                    if not pd.isna(df_numeric.iloc[end1 + 1, len(df.columns) - 1]):
                        CY_bal = df_numeric.iloc[end1 + 1, len(df.columns) - 1]
                if end1 + 1 < len(df_numeric) and len(df_numeric.columns) > 1:
                    if not pd.isna(df_numeric.iloc[end1 + 1, 1]):
                        PY_bal = df_numeric.iloc[end1 + 1, 1]
                self.cross_check_with_BSPL(
                    df,
                    cross_ref_marks,
                    issues,
                    account_name,
                    CY_bal,
                    PY_bal,
                    end1 + 1,
                    len(df.columns) - 1,
                    0,
                    (len(df.columns) - 1) - 1,
                )
                if self.context:
                    self.context.marks.add(account_name)
                # Backward compat: also populate global marks
                cross_check_marks.add(account_name)

        elif any(
            term in heading_lower
            for term in [
                "short-term borrowings",
                "short-term bonds",
                "short-term borrowing",
                "short-term bond",
            ]
        ):
            account_name = heading_lower
            if self.context and account_name and account_name not in self.context.marks:
                search_col_and_cross_ref("carrying", account_name, end1 + 1)
