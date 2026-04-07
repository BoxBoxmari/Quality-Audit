"""
Cash Flow validator implementation.
"""

import logging
import re
from typing import Dict, List, Optional, Tuple

import pandas as pd

from ...config.feature_flags import get_feature_flags
from ...core.legacy_audit.cash_flow import CASH_FLOW_CODE_FORMULAS
from ...utils.column_detector import ColumnDetector
from ...utils.numeric_utils import parse_numeric
from ..cache_manager import AuditContext, cross_check_cache
from .base_validator import BaseValidator, ValidationResult

logger = logging.getLogger(__name__)


class CashFlowValidator(BaseValidator):
    """Validator for cash flow statement."""

    _CODE_PATTERN = re.compile(r"^[0-9]{1,4}[A-Z]?$")

    def _extract_effective_code_from_row(
        self, row: pd.Series, candidate_code_columns: List[str]
    ) -> str:
        """Resolve code from declared/effective/rescued columns, then row-level inference."""
        canonical_col = "__canonical_code__"
        if canonical_col in row.index:
            candidate = str(row.get(canonical_col, "")).strip()
            norm_candidate = re.sub(r"\s+", "", candidate)
            if candidate and self._CODE_PATTERN.match(norm_candidate):
                return norm_candidate

        for col in candidate_code_columns:
            if col not in row.index:
                continue
            candidate = str(row.get(col, "")).strip()
            norm_candidate = re.sub(r"\s+", "", candidate)
            if candidate and self._CODE_PATTERN.match(norm_candidate):
                return norm_candidate

        for v in list(row.values)[: min(4, len(row.values))]:
            candidate = str(v).strip()
            norm_candidate = re.sub(r"\s+", "", candidate)
            if candidate and self._CODE_PATTERN.match(norm_candidate):
                return norm_candidate
        return ""

    def _parse_explicit_formula_tokens(self, label: str) -> Optional[List[str]]:
        """
        Parse inline formula tokens from row label, e.g.:
        "30 = 21 + 22 - 25 - 26" -> ["21", "22", "-25", "-26"].
        """
        text = str(label or "")
        m = re.search(r"=\s*([0-9A-Za-z+\-\s]+)", text)
        if not m:
            return None
        rhs = m.group(1)
        tokens = re.findall(r"[+\-]?\s*[0-9]+[A-Za-z]?", rhs)
        parsed: List[str] = []
        for tok in tokens:
            t = tok.replace(" ", "")
            if not t:
                continue
            sign = "-" if t.startswith("-") else ""
            code = t.lstrip("+-")
            if self._CODE_PATTERN.match(code):
                parsed.append(f"{sign}{code}")
        return parsed or None

    def _resolve_formula_children(
        self,
        parent_code: str,
        present_codes: set[str],
        row_label_map: Dict[str, str],
        heading: str,
    ) -> Tuple[List[str], str]:
        """
        Resolve formula terms in strict order:
        1) explicit inline formula from row label
        2) section profile
        3) present-code composition
        """
        explicit = self._parse_explicit_formula_tokens(
            row_label_map.get(parent_code, "")
        )
        if explicit:
            return explicit, "explicit_inline_formula"

        profiles: Dict[str, List[str]] = {
            k: list(v) for k, v in CASH_FLOW_CODE_FORMULAS.items()
        }
        if parent_code in profiles:
            prof = profiles[parent_code]
            present_profile = [c for c in prof if c in present_codes]
            # Keep strict formula when profile coverage is materially present.
            #
            # Special-case: legacy code "18" is an "indirect adjustment block" subtotal in some
            # templates, but in other templates the row above codes 14–17 is a different subtotal.
            # If we only see 2/4 components, validating "18" becomes error-prone (e.g., treating
            # interest+tax paid as a subtotal). Require higher coverage for "18".
            if parent_code == "18" and len(present_profile) < 3:
                return [], "section_profile_insufficient_coverage"

            if len(present_profile) >= max(2, min(4, len(prof) // 2)):
                return present_profile, "section_profile"

        flags = get_feature_flags()
        if not flags.get("nonbaseline_present_code_composition", False):
            return [
                c for c in profiles.get(parent_code, []) if c in present_codes
            ], "legacy_profile_only"

        # Non-baseline composition fallback (explicitly feature-flagged).
        if parent_code == "08":
            return [
                c
                for c in ["01", "02", "03", "04", "05", "06", "07"]
                if c in present_codes
            ], "present_code_composition"
        if parent_code == "30":
            return [
                c
                for c in ["21", "22", "23", "24", "25", "26", "27"]
                if c in present_codes
            ], "present_code_composition"
        if parent_code == "20":
            return [
                c
                for c in ["08", "09", "10", "11", "12", "13", "14", "15", "16", "17"]
                if c in present_codes
            ], "present_code_composition"
        if parent_code == "40":
            return [
                c for c in ["31", "32", "33", "34", "35", "36"] if c in present_codes
            ], "present_code_composition"
        if parent_code == "50":
            return [
                c for c in ["20", "30", "40"] if c in present_codes
            ], "present_code_composition"
        if parent_code == "70":
            return [
                c for c in ["50", "60", "61"] if c in present_codes
            ], "present_code_composition"
        return [], "unresolved"

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
            code_col = metadata.get("effective_code_column") or metadata.get(
                "code_column"
            )
            declared_code_col = metadata.get("declared_code_column")
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
            if not code_col and "__canonical_code__" in df_norm.columns:
                code_col = "__canonical_code__"

            # Guardrail: never accept "Description"-like columns as code columns unless
            # they actually contain code-shaped tokens with meaningful density.
            if code_col and "description" in str(code_col).strip().lower():
                ser = df_norm[code_col].astype(object)
                sample = [
                    re.sub(r"\s+", "", str(v).strip())
                    for v in ser.dropna().head(25).tolist()
                ]
                code_hits = sum(1 for v in sample if v and self._CODE_PATTERN.match(v))
                if code_hits < 3:
                    code_col = None

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
                    status_enum="WARN",
                    context={"failure_reason_code": rule_id, **metadata},
                )

            # Use normalized dataframe
            tmp = df_norm
            header = list(tmp.columns)
            header_idx = -1
            code_candidates: List[str] = []
            for c in (declared_code_col, code_col):
                if c and c in tmp.columns and c not in code_candidates:
                    code_candidates.append(c)
            for entry in (metadata.get("code_column_evidence") or {}).get(
                "candidates", []
            ):
                name = str(entry.get("column") or "").strip()
                ratio = float(entry.get("code_match_ratio") or 0.0)
                if name not in tmp.columns or name in code_candidates:
                    continue
                ser = pd.to_numeric(
                    tmp[name].astype(object).map(parse_numeric), errors="coerce"
                ).dropna()
                median_abs = float(ser.abs().median()) if len(ser) else 0.0
                if ratio >= 0.45 and (median_abs <= 999 or median_abs == 0.0):
                    code_candidates.append(name)

            # P2-T1: Ensure we assign the detected columns for downstream use if possible
            # Currently the rest of the code re-detects columns, so we just provide tmp.

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
                    status_enum="WARN",
                    context={"failure_reason_code": rule_id, **metadata},
                )

            # Find numeric columns using metadata first and exclude effective code columns.
            cur_col = metadata.get("current_year_column")
            prior_col = metadata.get("prior_year_column")
            if (
                not cur_col
                or not prior_col
                or cur_col == code_col
                or prior_col == code_col
            ):
                candidate_cols = [
                    c
                    for c in tmp.columns
                    if c not in {code_col, declared_code_col}
                    and str(c).strip().lower() not in {"code", "mã", "mã số"}
                ]
                cur_col, prior_col = ColumnDetector.detect_financial_columns_advanced(
                    tmp[candidate_cols] if len(candidate_cols) >= 2 else tmp
                )
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
            row_label_map: Dict[str, str] = {}

            for ridx, row in tmp.iterrows():
                code = self._normalize_code(
                    self._extract_effective_code_from_row(row, code_candidates)
                )
                cur_val = parse_numeric(row.get(cur_col, ""))
                prior_val = parse_numeric(row.get(prior_col, ""))
                row_label = str(row.iloc[0]).strip() if len(row) else ""

                # Cache all rows for special case handling
                rows_cache.append((ridx, code, cur_val, prior_val))

                # Only aggregate valid codes at table level
                if code and re.match(r"^[0-9]{1,4}[A-Z]?$", code):
                    data_map[code].append((cur_val, prior_val, ridx))
                    if code not in row_label_map and row_label:
                        row_label_map[code] = row_label

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
            formula_profile: Dict[str, str] = {}

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
            present_codes = set(aggregated_data.keys())
            for parent in ("08", "18", "20", "30", "40", "50", "70"):
                if parent not in present_codes:
                    continue
                children, profile = self._resolve_formula_children(
                    parent, present_codes, row_label_map, heading or ""
                )
                formula_profile[parent] = profile
                if children:
                    check(parent, children)
            self._reconcile_code_70_to_cash_equivalents(
                aggregated_data=aggregated_data,
                data_map=data_map,
                marks=marks,
                issues=issues,
                cur_col_pos=cur_col_pos,
                prior_col_pos=prior_col_pos,
            )

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
            if isinstance(result.context, dict):
                result.context["declared_code_column"] = declared_code_col
                result.context["effective_code_column"] = code_col
                result.context["effective_code_sources"] = code_candidates
                result.context["group_scope_used"] = bool(
                    flags.get("cashflow_cross_table_context", False)
                    and context is not None
                    and bool(context.cash_flow_registry)
                )
                result.context["formula_profile"] = formula_profile
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
            sign = -1 if token.startswith("-") else 1
            code = token[1:] if token.startswith("-") else token
            cn = self._normalize_code(code)

            if cn in data:
                ccur, cprior = data[cn]
                cur_sum += sign * ccur
                prior_sum += sign * cprior
                have_any = True
            else:
                missing.append(cn)

        return have_any, cur_sum, prior_sum, missing

    def _reconcile_code_70_to_cash_equivalents(
        self,
        aggregated_data: Dict[str, Tuple[float, float]],
        data_map: Dict[str, List[tuple]],
        marks: List[Dict],
        issues: List[str],
        cur_col_pos: int,
        prior_col_pos: int,
    ) -> None:
        """
        Reconcile cash flow code 70 against cached cash/cash-equivalent ending balance
        when such evidence is available from statements/notes.
        """
        if "70" not in aggregated_data:
            return

        candidate_keys = [
            "cash and cash equivalents",
            "cash and cash equivalents at end of year",
            "cash and cash equivalents at end of period",
            "cash and cash equivalents ending balance",
        ]
        fs_balance = None
        fs_key = None
        for key in candidate_keys:
            val = cross_check_cache.get(key)
            if val is not None:
                fs_balance = val
                fs_key = key
                break
        if fs_balance is None:
            return

        cf_cur, cf_pr = aggregated_data["70"]
        bs_cur, bs_pr = fs_balance
        dcur = cf_cur - float(bs_cur)
        dpr = cf_pr - float(bs_pr)
        ok_cur = abs(round(dcur)) == 0
        ok_pr = abs(round(dpr)) == 0
        if ok_cur and ok_pr:
            return

        comment = (
            "70 reconciliation with cash equivalents"
            f" [{fs_key}]: CF={cf_cur:,.0f}/{cf_pr:,.0f}; "
            f"FS={float(bs_cur):,.0f}/{float(bs_pr):,.0f}; "
            f"Δ={dcur:,.0f}/{dpr:,.0f}"
        )
        if "70" in data_map:
            for _, _, ridx in data_map["70"]:
                marks.append(
                    {
                        "row": ridx,
                        "col": cur_col_pos,
                        "ok": ok_cur,
                        "comment": None if ok_cur else comment,
                    }
                )
                marks.append(
                    {
                        "row": ridx,
                        "col": prior_col_pos,
                        "ok": ok_pr,
                        "comment": None if ok_pr else comment,
                    }
                )
        issues.append(comment)
