"""
Income Statement validator implementation.
"""

import re
from typing import Dict, List

import pandas as pd

from ...utils.column_detector import ColumnDetector
from ...utils.numeric_utils import parse_numeric
from ..cache_manager import cross_check_cache
from .base_validator import BaseValidator, ValidationResult


class IncomeStatementValidator(BaseValidator):
    """Validator for income statement financial statements."""

    def validate(self, df: pd.DataFrame, heading: str = None) -> ValidationResult:
        """
        Validate income statement table.

        Args:
            df: DataFrame containing income statement data
            heading: Table heading (unused)

        Returns:
            ValidationResult: Validation results
        """
        # Find header row
        header_idx = self._find_header_row(df, "code")
        if header_idx is None:
            return ValidationResult(
                status="WARN: Statement of income - không tìm thấy cột 'Code' để kiểm tra",
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
                status="WARN: Statement of income - không xác định được cột 'Code'",
                marks=[],
                cross_ref_marks=[],
            )

        note_col = next(
            (c for c in tmp.columns if str(c).strip().lower() == "note"), None
        )

        # Find numeric columns using advanced column detection
        cur_col, prior_col = ColumnDetector.detect_financial_columns_advanced(tmp)
        if cur_col is None or prior_col is None:
            # Fallback to last two columns if detection fails
            cur_col, prior_col = tmp.columns[-2], tmp.columns[-1]

        # Build data map
        data = {}
        code_rowpos = {}

        for ridx, row in tmp.iterrows():
            code = self._normalize_code(row.get(code_col, ""))
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

            # Cross-check cache logic: store account names and special codes
            if row.get(note_col, "") != "":
                acc_name = row.get(tmp.columns[0]).strip().lower()
                cross_check_cache.set(acc_name, (cur_val, prior_val))

                # Aggregate codes '51' and '52' into "income tax"
                if code in ["51", "52"]:
                    cached_income_tax = cross_check_cache.get("income tax")
                    if cached_income_tax:
                        old_cur, old_pr = cached_income_tax
                    else:
                        old_cur, old_pr = 0.0, 0.0
                    cross_check_cache.set(
                        "income tax", (cur_val + old_cur, prior_val + old_pr)
                    )
            else:
                # Store code '50' in cache for tax reconciliation cross-check
                if code == "50":
                    cross_check_cache.set("50", (cur_val, prior_val))

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

        # Apply income statement rules
        check("10", ["01", "-02"])
        check("20", ["10", "-11"])
        check("20", ["01", "-02", "-11"])
        check("30", ["20", "21", "-22", "24", "-25", "-26"])
        check("40", ["31", "-32"])
        check("50", ["30", "40"])
        check("60", ["50", "-51", "-52"])
        check("60", ["61", "62"])

        # Generate status
        if not issues:
            status = "PASS: Statement of income - kiểm tra công thức: KHỚP (0 sai lệch)"
        else:
            preview = "; ".join(issues[:10])
            more = f" ... (+{len(issues) - 10} dòng)" if len(issues) > 10 else ""
            status = f"FAIL: Statement of income - kiểm tra công thức: {
                len(issues)} sai lệch. {preview}{more}"

        return ValidationResult(status=status, marks=marks, cross_ref_marks=[])

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
