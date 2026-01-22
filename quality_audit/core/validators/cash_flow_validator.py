"""
Cash Flow validator implementation.
"""

import re
from typing import Dict, List

import pandas as pd

from ...utils.column_detector import ColumnDetector
from ...utils.numeric_utils import parse_numeric
from .base_validator import BaseValidator, ValidationResult


class CashFlowValidator(BaseValidator):
    """Validator for cash flow statement."""

    def validate(self, df: pd.DataFrame, heading: str = None) -> ValidationResult:
        """
        Validate cash flow statement table.

        Args:
            df: DataFrame containing cash flow data
            heading: Table heading (unused)

        Returns:
            ValidationResult: Validation results
        """
        # Find header row
        header_idx = self._find_header_row(df, "code")
        if header_idx is None:
            return ValidationResult(
                status="WARN: Cash flows - không tìm thấy cột 'Code' để kiểm tra",
                marks=[],
                cross_ref_marks=[],
            )

        # Extract data with proper headers
        header = [str(c).strip() for c in df.iloc[header_idx].tolist()]
        tmp = df.iloc[header_idx + 1:].copy()
        tmp.columns = header
        tmp = tmp.reset_index(drop=True)

        # Identify columns
        code_col = next(
            (c for c in tmp.columns if str(c).strip().lower() == "code"), None
        )
        if code_col is None:
            return ValidationResult(
                status="WARN: Cash flows - không xác định được cột 'Code'",
                marks=[],
                cross_ref_marks=[],
            )

        # Find numeric columns using advanced column detection
        cur_col, prior_col = ColumnDetector.detect_financial_columns_advanced(tmp)
        if cur_col is None or prior_col is None:
            # Fallback to last two columns if detection fails
            cur_col, prior_col = tmp.columns[-2], tmp.columns[-1]

        # Build data map
        data = {}
        code_rowpos = {}
        rows_cache = []

        for ridx, row in tmp.iterrows():
            code = self._normalize_code(row.get(code_col, ""))
            cur_val = parse_numeric(row.get(cur_col, ""))
            prior_val = parse_numeric(row.get(prior_col, ""))

            # Cache all rows for special case handling
            rows_cache.append((ridx, code, cur_val, prior_val))

            # Only aggregate valid codes
            if code and re.match(r"^[0-9]+[A-Z]?$", code):
                agg_cur, agg_pr = data.get(code, (0.0, 0.0))
                data[code] = (agg_cur + cur_val, agg_pr + prior_val)
                code_rowpos.setdefault(code, ridx)

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
                data["18"] = (prev_cur, prev_pr)
                code_rowpos.setdefault("18", idx18)

        # Get column positions
        try:
            cur_col_pos = header.index(cur_col)
            prior_col_pos = header.index(prior_col)
        except ValueError:
            cur_col_pos = len(header) - 2
            prior_col_pos = len(header) - 1

        # Validate cash flow rules
        issues = []
        marks = []

        def check(parent, children, label=None):
            parent_norm = self._normalize_code(parent)
            if parent_norm not in data:
                return

            have_any, cur_sum, prior_sum, missing = self._sum_weighted(data, children)
            if not have_any:
                return

            ac_cur, ac_pr = data[parent_norm]
            dc = cur_sum - ac_cur
            dp = prior_sum - ac_pr
            is_ok_cy = abs(dc) < 0.01
            is_ok_py = abs(dp) < 0.01

            if parent_norm in code_rowpos:
                df_row = header_idx + 1 + code_rowpos[parent_norm]
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

        # Apply cash flow rules
        check("08", ["01", "02", "03", "04", "05", "06", "07"])
        if "18" in data:
            check("18", ["08", "09", "10", "11", "12", "13"])
        check("20", ["08", "09", "10", "11", "12", "13", "14", "15", "16", "17"])
        check("30", ["21", "22", "23", "24", "25", "26", "27"])
        check("40", ["31", "32", "33", "34", "35", "36"])
        check("50", ["20", "30", "40"])
        check("70", ["50", "60", "61"])

        # Generate status
        if not issues:
            status = (
                "PASS: Statement of cash flows - kiểm tra công thức: KHỚP (0 sai lệch)"
            )
        else:
            preview = "; ".join(issues[:10])
            more = f" ... (+{len(issues) - 10} dòng)" if len(issues) > 10 else ""
            status = f"FAIL: Statement of cash flows - kiểm tra công thức: {
                len(issues)} sai lệch. {preview}{more}"

        return ValidationResult(status=status, marks=marks, cross_ref_marks=[])

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
