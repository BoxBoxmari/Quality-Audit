"""
Income Statement validator implementation.
"""

import logging
import re
from typing import Dict, List, Optional

import pandas as pd

from ...utils.column_detector import ColumnDetector
from ...utils.numeric_utils import parse_numeric
from ..cache_manager import cross_check_cache
from .base_validator import BaseValidator, ValidationResult

logger = logging.getLogger(__name__)


class IncomeStatementValidator(BaseValidator):
    """Validator for income statement financial statements."""

    def validate(
        self,
        df: pd.DataFrame,
        heading: Optional[str] = None,
        table_context: Optional[Dict] = None,
    ) -> ValidationResult:
        """
        Validate income statement table.

        Args:
            df: DataFrame containing income statement data
            heading: Table heading (unused)
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
            # Fallback: if first row is a header row but dataframe has positional columns,
            # promote it to headers before normalization.
            if df is not None and not df.empty:
                try:
                    first_row = df.iloc[0].astype(str).str.strip().str.lower().tolist()
                except Exception:
                    first_row = []
                if any(v == "code" for v in first_row):
                    df_promoted = df.copy()
                    df_promoted.columns = df_promoted.iloc[0].astype(str)
                    df_promoted = df_promoted.iloc[1:].reset_index(drop=True)
                    df_norm, metadata = self._normalize_table_with_metadata(
                        df_promoted, heading, table_context
                    )
                else:
                    df_norm, metadata = self._normalize_table_with_metadata(
                        df, heading, table_context
                    )
            else:
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
                    status="WARN: Statement of income - không tìm thấy cột 'Code' để kiểm tra",
                    marks=[],
                    cross_ref_marks=[],
                    rule_id=rule_id,
                    status_enum="INFO_SKIPPED",
                    context={"failure_reason_code": rule_id, **metadata},
                )

            # Safety override: if there is an explicit "Code" column, always prefer it.
            # This validator's cache and rule checks rely on numeric account codes.
            explicit_code_col = next(
                (c for c in df_norm.columns if str(c).strip().lower() == "code"), None
            )
            if explicit_code_col is not None:
                code_col = explicit_code_col

            # Use normalized dataframe
            tmp = df_norm
            header = list(tmp.columns)
            header_idx = -1

            # P2-T1: Ensure we assign the detected columns for downstream use if possible
            # Currently the rest of the code re-detects columns, so we just provide tmp.

            # Use the detected code column from normalization (do not re-restrict to literal "code")
            if code_col is None:
                canon = metadata.get("canon_report") or {}
                flags = canon.get("flags") or {}
                rule_id = (
                    "UNDETERMINED_HEADER_AFTER_CANONICALIZE"
                    if metadata.get("canonicalization_applied") and flags
                    else "MISSING_CODE_COLUMN"
                )
                return ValidationResult(
                    status="WARN: Statement of income - không xác định được cột 'Code'",
                    marks=[],
                    cross_ref_marks=[],
                    rule_id=rule_id,
                    status_enum="INFO_SKIPPED",
                    context={"failure_reason_code": rule_id, **metadata},
                )

            note_col = next(
                (c for c in tmp.columns if str(c).strip().lower() == "note"), None
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

            # Build data maps
            data: Dict[str, tuple] = {}
            code_rowpos: Dict[str, int] = {}
            custom_formulas: Dict[str, List[str]] = {}

            label_cols = metadata.get("label_cols", [])

            for ridx, row in tmp.iterrows():
                # P5: Extract custom inline formulas from descriptions
                if label_cols:
                    for l_col in label_cols:
                        cell_val = row.get(l_col)
                        if pd.notna(cell_val):
                            parsed = self._parse_inline_formula(str(cell_val))
                            if parsed:
                                t_code, c_list = parsed
                                # Normalize target code before storing
                                t_code_norm = self._normalize_code(t_code)
                                custom_formulas[t_code_norm] = c_list
                                logger.info(
                                    "Parsed custom formula for %s: %s",
                                    t_code_norm,
                                    c_list,
                                )
                                break

                code_raw = row.get(code_col)
                code = self._normalize_code(code_raw)
                if not code or not re.match(r"^[0-9]+[A-Z]?$", code):
                    continue

                cur_val = parse_numeric(row.get(cur_col, ""))
                prior_val = parse_numeric(row.get(prior_col, ""))

                if code in data:
                    old_cur, old_pr = data[code]
                    if (
                        abs(cur_val) + abs(prior_val) == 0
                        and abs(old_cur) + abs(old_pr) != 0
                    ):
                        continue

                data[code] = (cur_val, prior_val)

                # Cross-check cache: always store by code (e.g., '50')
                cross_check_cache.set(code, (cur_val, prior_val))

                # Store account name when there is a Note reference
                if note_col is not None and str(row.get(note_col, "")).strip() != "":
                    # Prefer a descriptive account/name column if present
                    account_col = next(
                        (
                            c
                            for c in tmp.columns
                            if str(c).strip().lower()
                            in {"account", "description", "item", "account name"}
                        ),
                        tmp.columns[0],
                    )
                    acc_name = str(row.get(account_col, "")).strip().lower()
                    if acc_name:
                        cross_check_cache.set(acc_name, (cur_val, prior_val))

                # Aggregate codes '51' and '52' into "income tax" (regardless of Note)
                if code in ["51", "52"]:
                    cached_income_tax = cross_check_cache.get("income tax")
                    if cached_income_tax:
                        old_cur, old_pr = cached_income_tax
                    else:
                        old_cur, old_pr = 0.0, 0.0
                    cross_check_cache.set(
                        "income tax", (cur_val + old_cur, prior_val + old_pr)
                    )

                code_rowpos.setdefault(code, ridx)

            # Get column positions
            try:
                cur_col_pos = header.index(cur_col)
                prior_col_pos = header.index(prior_col)
            except ValueError:
                cur_col_pos = len(header) - 2
                prior_col_pos = len(header) - 1

            # Validate income statement rules
            issues = []
            marks = []

            def check(parent, default_children, label=None):
                parent_norm = self._normalize_code(parent)
                if parent_norm not in data:
                    return

                children = custom_formulas.get(parent_norm, default_children)

                have_any, cur_sum, prior_sum, missing = self._sum_weighted(
                    data, children
                )
                if not have_any:
                    return

                ac_cur, ac_pr = data[parent_norm]
                dc = cur_sum - ac_cur
                dp = prior_sum - ac_pr
                is_ok_cy = abs(round(dc)) == 0
                is_ok_py = abs(round(dp)) == 0

                if parent_norm in code_rowpos:
                    # SCRUM-11: If header_idx = -1, header already promoted, no offset needed
                    df_row = (
                        (header_idx + 1 + code_rowpos[parent_norm])
                        if header_idx >= 0
                        else code_rowpos[parent_norm]
                    )
                    comment = (
                        f"{parent_norm} = {' + '.join(children).replace('+ -', ' - ')}; "
                        f"Tính={cur_sum:,.0f}/{prior_sum:,.0f}; Thực tế={ac_cur:,.0f}/{ac_pr:,.0f}; Δ={dc:,.0f}/{dp:,.0f}"
                        + (f"; Thiếu={','.join(missing)}" if missing else "")
                    )
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

            # SCRUM-12: Template selection - check if code 10 exists to determine template
            # Template 1: Has code 10 -> check 10=01-02, 20=10-11
            # Template 2: No code 10 -> check 20=01-11 (or 20=01-02-11)
            has_code_10 = "10" in data

            # Apply income statement rules with template selection
            if has_code_10:
                # Template 1: Has code 10
                check("10", ["01", "-02"])
                check("20", ["10", "-11"])
            else:
                # Template 2: No code 10 -> use alternative formula
                check("20", ["01", "-02", "-11"])

            # Common rules for both templates
            check("30", ["20", "21", "-22", "24", "-25", "-26"])
            check("40", ["31", "-32"])
            check("50", ["30", "40"])
            check("60", ["50", "-51", "-52"])
            check("60", ["61", "62"])

            # Generate status
            if not issues:
                status = (
                    "PASS: Statement of income - kiểm tra công thức: KHỚP (0 sai lệch)"
                )
            else:
                preview = "; ".join(issues[:10])
                more = f" ... (+{len(issues) - 10} dòng)" if len(issues) > 10 else ""
                status = f"FAIL: Statement of income - kiểm tra công thức: {len(issues)} sai lệch. {preview}{more}"

            result = ValidationResult(
                status=status,
                marks=marks,
                cross_ref_marks=[],
                detected_columns=list(tmp.columns),
                root_cause="Calculation Mismatch" if issues else None,
                table_id="Income Statement",
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
            logger.exception("Income statement validator logic failed")
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
        """Calculate weighted sum for income statement rules."""
        have_any = False
        cur_sum = prior_sum = 0.0
        missing = []

        for token in children:
            token = str(token).strip()
            sign = -1 if token.startswith("-") else 1
            code = token[1:] if sign == -1 else token
            cn = self._normalize_code(code)

            if cn in data:
                ccur, cprior = data[cn]
                cur_sum += sign * ccur
                prior_sum += sign * cprior
                have_any = True
            else:
                missing.append(cn if sign == 1 else f"-{cn}")

        return have_any, cur_sum, prior_sum, missing

    def _parse_inline_formula(self, text: str) -> Optional[tuple[str, list[str]]]:
        """
        Parse inline formula from row description.
        Example: "Lợi nhuận (30 = 20 + (21-22) - 25 - 26)" -> ("30", ["20", "21", "-22", "-25", "-26"])
        """
        if not isinstance(text, str):
            return None

        match = re.search(r"(\d{2})\s*=\s*([0-9\s\+\-\(\)]+)", text)
        if not match:
            return None

        target_code = match.group(1).strip()
        expression = match.group(2).strip()

        clean_exp = expression.replace(" ", "")
        # Remove trailing unclosed parenthesis if any (can happen if regex consumes the closing bracket of the text)
        if clean_exp.endswith(")") and clean_exp.count("(") < clean_exp.count(")"):
            clean_exp = clean_exp[:-1]

        children = []
        current_sign = 1
        sign_stack = [1]

        tokens = re.findall(r"(\d{2}|\+|\-|\(|\))", clean_exp)

        for token in tokens:
            if token == "+":
                current_sign = 1
            elif token == "-":
                current_sign = -1
            elif token == "(":
                effective_sign = sign_stack[-1] * current_sign
                sign_stack.append(effective_sign)
                current_sign = 1
            elif token == ")":
                if len(sign_stack) > 1:
                    sign_stack.pop()
            elif re.match(r"^\d{2}$", token):
                eff_sign = sign_stack[-1] * current_sign
                if eff_sign == 1:
                    children.append(token)
                else:
                    children.append("-" + token)
                current_sign = 1

        if not children:
            return None

        return target_code, children
