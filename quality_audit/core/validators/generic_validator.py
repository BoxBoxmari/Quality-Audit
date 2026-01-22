"""
Generic table validator for standard financial tables.
"""

from typing import Dict, List, Optional

import pandas as pd

from ...config.constants import (CROSS_CHECK_TABLES_FORM_1,
                                 CROSS_CHECK_TABLES_FORM_2,
                                 CROSS_CHECK_TABLES_FORM_3,
                                 TABLES_NEED_CHECK_SEPARATELY,
                                 TABLES_NEED_COLUMN_CHECK,
                                 TABLES_WITHOUT_TOTAL)
from ...utils.numeric_utils import normalize_numeric_column
from ..cache_manager import cross_check_marks
from .base_validator import BaseValidator, ValidationResult


class GenericTableValidator(BaseValidator):
    """Generic validator for standard financial tables."""

    def validate(
        self, df: pd.DataFrame, heading: Optional[str] = None
    ) -> ValidationResult:
        """
        Validate generic financial table.

        Args:
            df: DataFrame containing table data
            heading: Table heading for context

        Returns:
            ValidationResult: Validation results
        """
        heading_lower = heading.lower().strip() if heading else ""

        # Check for special table types that should be skipped
        if self._should_skip_table(df, heading_lower):
            return ValidationResult(
                status="INFO: Bảng không bao gồm số/số tổng",
                marks=[],
                cross_ref_marks=[],
            )

        # Standard table validation
        return self._validate_standard_table(df, heading_lower)

    def _should_skip_table(self, df: pd.DataFrame, heading_lower: str) -> bool:
        """Check if table should be skipped from validation."""
        # Check heading-based rules
        if heading_lower in TABLES_WITHOUT_TOTAL:
            return True

        # Check if table has insufficient numeric data
        subset = df.iloc[2:]  # Skip header rows
        numeric_content = subset.map(
            lambda x: pd.to_numeric(
                str(x).replace(",", "").replace("(", "-").replace(")", ""),
                errors="coerce",
            )
        )
        return numeric_content.isna().all().all()

    def _validate_standard_table(
        self, df: pd.DataFrame, heading_lower: str
    ) -> ValidationResult:
        """Validate standard table with totals."""
        df_numeric = df.map(normalize_numeric_column)
        total_row_idx = self._find_total_row(df)

        if total_row_idx is None and not self._needs_column_check(heading_lower):
            return ValidationResult(
                status="INFO: Bảng không có dòng/cột tổng", marks=[], cross_ref_marks=[]
            )

        last_col_idx = len(df.columns) - 1
        check_column_total = heading_lower in [
            name.lower() for name in TABLES_NEED_COLUMN_CHECK
        ]
        check_separately_total = heading_lower in [
            name.lower() for name in TABLES_NEED_CHECK_SEPARATELY
        ]

        issues = []
        marks = []
        cross_ref_marks = []

        if check_separately_total:
            # Fixed assets validation (simplified)
            result = self._validate_fixed_assets(df, df_numeric, heading_lower)
            return result
        elif check_column_total and last_col_idx > 1:
            # Column total validation
            self._validate_column_totals(
                df_numeric, total_row_idx, last_col_idx, marks, issues
            )
        else:
            # Standard row total validation
            self._validate_row_totals(
                df,
                df_numeric,
                total_row_idx,
                heading_lower,
                marks,
                issues,
                cross_ref_marks,
            )

        # Generate status
        if not issues:
            status = "PASS: Kiểm tra công thức: KHỚP (0 sai lệch)"
        else:
            preview = "; ".join(issues[:10])
            more = f" ... (+{len(issues) - 10} dòng)" if len(issues) > 10 else ""
            status = (
                f"FAIL: Kiểm tra công thức: {len(issues)} sai lệch. {preview}{more}"
            )

        return ValidationResult(
            status=status, marks=marks, cross_ref_marks=cross_ref_marks
        )

    def _needs_column_check(self, heading_lower: str) -> bool:
        """Check if table needs column-based validation."""
        return heading_lower in [name.lower() for name in TABLES_NEED_COLUMN_CHECK]

    def _validate_fixed_assets(
        self, df: pd.DataFrame, df_numeric: pd.DataFrame, heading_lower: str
    ) -> ValidationResult:
        """Validate fixed assets table with cost, accumulated depreciation, and NBV."""
        # Find rows containing keywords
        cost_keywords = ["cost", "giá vốn"]
        AD_keywords = [
            "accumulated depreciation",
            "accumulated amortisation",
            "khấu hao lũy kế",
            "hao mòn lũy kế",
        ]
        NBV_keywords = ["net book value", "giá trị còn lại"]

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
        cost_detail_sum = df_numeric.iloc[
            cost_start_row_idx: AD_start_row_idx - 2
        ].sum(skipna=True)
        cost_total_row = df_numeric.iloc[AD_start_row_idx - 1]
        AD_detail_sum = df_numeric.iloc[AD_start_row_idx: NBV_start_row_idx - 2].sum(
            skipna=True
        )
        AD_total_row = df_numeric.iloc[NBV_start_row_idx - 1]
        OB_detail_cal = (
            df_numeric.iloc[cost_start_row_idx + 1]
            - df_numeric.iloc[AD_start_row_idx + 1]
        )
        CB_detail_cal = cost_total_row - AD_total_row
        OB_NBV_total_row = df_numeric.iloc[NBV_start_row_idx + 1]
        CB_NBV_total_row = df_numeric.iloc[NBV_start_row_idx + 2]

        issues = []
        marks = []
        cross_ref_marks = []

        # Validate cost totals
        for col in range(len(df.columns)):
            if not pd.isna(cost_total_row[col]) and not pd.isna(cost_detail_sum[col]):
                diff = cost_detail_sum[col] - cost_total_row[col]
                is_ok = abs(round(diff)) == 0
                comment = f"DÒNG TỔNG (GV) - Cột {
                    col +
                    1}: Tính lại={
                    cost_detail_sum[col]:,.2f}, Trên bảng={
                    cost_total_row[col]:,.2f}, Sai lệch={
                    diff:,.2f}"
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
            if not pd.isna(AD_total_row[col]) and not pd.isna(AD_detail_sum[col]):
                diff = AD_detail_sum[col] - AD_total_row[col]
                is_ok = abs(round(diff)) == 0
                comment = f"DÒNG TỔNG (AD) - Cột {
                    col +
                    1}: Tính lại={
                    AD_detail_sum[col]:,.2f}, Trên bảng={
                    AD_total_row[col]:,.2f}, Sai lệch={
                    diff:,.2f}"
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
                not pd.isna(OB_NBV_total_row[col])
                and not pd.isna(CB_NBV_total_row[col])
                and not pd.isna(OB_detail_cal[col])
                and not pd.isna(CB_detail_cal[col])
            ):
                diffOB = OB_detail_cal[col] - OB_NBV_total_row[col]
                diffCB = CB_detail_cal[col] - CB_NBV_total_row[col]
                is_okOB = abs(round(diffOB)) == 0
                is_okCB = abs(round(diffCB)) == 0

                commentOB = f"DÒNG TỔNG (OB NBV) - Cột {
                    col +
                    1}: Tính lại={
                    OB_detail_cal[col]:,.2f}, Trên bảng={
                    OB_NBV_total_row[col]:,.2f}, Sai lệch={
                    diffOB:,.2f}"
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

                commentCB = f"DÒNG TỔNG (CB NBV) - Cột {
                    col +
                    1}: Tính lại={
                    CB_detail_cal[col]:,.2f}, Trên bảng={
                    CB_NBV_total_row[col]:,.2f}, Sai lệch={
                    diffCB:,.2f}"
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

        # Cross-check NBV with BSPL
        account_name = heading_lower
        CY_bal = (
            df_numeric.iloc[NBV_start_row_idx + 2, len(df.columns) - 1]
            if not pd.isna(df_numeric.iloc[NBV_start_row_idx + 2, len(df.columns) - 1])
            else 0
        )
        PY_bal = (
            df_numeric.iloc[NBV_start_row_idx + 1, len(df.columns) - 1]
            if not pd.isna(df_numeric.iloc[NBV_start_row_idx + 1, len(df.columns) - 1])
            else 0
        )
        if account_name not in cross_check_marks:
            self.cross_check_with_BSPL(
                df,
                cross_ref_marks,
                issues,
                account_name,
                CY_bal,
                PY_bal,
                NBV_start_row_idx + 2,
                len(df.columns) - 1,
                1,
                0,
            )
            cross_check_marks.add(account_name)

        # Cross-check Cost with BSPL accounts
        CY_bal = (
            df_numeric.iloc[AD_start_row_idx - 1, len(df.columns) - 1]
            if not pd.isna(df_numeric.iloc[AD_start_row_idx - 1, len(df.columns) - 1])
            else 0
        )
        PY_bal = (
            df_numeric.iloc[cost_start_row_idx + 1, len(df.columns) - 1]
            if not pd.isna(df_numeric.iloc[cost_start_row_idx + 1, len(df.columns) - 1])
            else 0
        )

        # Map heading to account code for cost
        if heading_lower == "tangible fixed assets":
            account_name = "222"
        elif heading_lower == "finance lease tangible fixed assets":
            account_name = "225"
        elif heading_lower == "intangible fixed assets":
            account_name = "228"
        elif heading_lower == "investment property":
            account_name = "231"
        else:
            account_name = None

        if account_name and account_name not in cross_check_marks:
            gap_row = AD_start_row_idx - 1 - (cost_start_row_idx + 1)
            self.cross_check_with_BSPL(
                df,
                cross_ref_marks,
                issues,
                account_name,
                CY_bal,
                PY_bal,
                AD_start_row_idx - 1,
                len(df.columns) - 1,
                gap_row,
                0,
            )
            cross_check_marks.add(account_name)

        # Cross-check Accumulated Depreciation with BSPL accounts
        CY_bal = (
            (df_numeric.iloc[NBV_start_row_idx - 1, len(df.columns) - 1] * -1)
            if not pd.isna(df_numeric.iloc[NBV_start_row_idx - 1, len(df.columns) - 1])
            else 0
        )
        PY_bal = (
            (df_numeric.iloc[AD_start_row_idx + 1, len(df.columns) - 1] * -1)
            if not pd.isna(df_numeric.iloc[AD_start_row_idx + 1, len(df.columns) - 1])
            else 0
        )

        # Map heading to account code for accumulated depreciation
        if heading_lower == "tangible fixed assets":
            account_name = "223"
        elif heading_lower == "finance lease tangible fixed assets":
            account_name = "226"
        elif heading_lower == "intangible fixed assets":
            account_name = "229"
        elif heading_lower == "investment property":
            account_name = "232"
        else:
            account_name = None

        if account_name and account_name not in cross_check_marks:
            gap_row = NBV_start_row_idx - 1 - (AD_start_row_idx + 1)
            self.cross_check_with_BSPL(
                df,
                cross_ref_marks,
                issues,
                account_name,
                CY_bal,
                PY_bal,
                NBV_start_row_idx - 1,
                len(df.columns) - 1,
                gap_row,
                0,
            )
            cross_check_marks.add(account_name)

        # Generate status
        if not issues:
            status = "PASS: Fixed assets - kiểm tra công thức: KHỚP (0 sai lệch)"
        else:
            preview = "; ".join(issues[:10])
            more = f" ... (+{len(issues) - 10} dòng)" if len(issues) > 10 else ""
            status = f"FAIL: Fixed assets - kiểm tra công thức: {
                len(issues)} sai lệch. {preview}{more}"

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
    ) -> None:
        """Validate column totals."""
        for i in range(total_row_idx + 1):
            row = df_numeric.iloc[i]
            row_sum = row.drop(labels=df_numeric.columns[last_col_idx]).sum(skipna=True)
            col_total_val = row.iloc[last_col_idx]

            if not pd.isna(col_total_val) and not pd.isna(row_sum):
                diff = row_sum - col_total_val
                is_ok = abs(round(diff)) == 0

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

    def _validate_row_totals(
        self,
        df: pd.DataFrame,
        df_numeric: pd.DataFrame,
        total_row_idx: int,
        heading_lower: str,
        marks: List[Dict],
        issues: List[str],
        cross_ref_marks: List[Dict],
    ) -> None:
        """Validate row totals and cross-references with block-sum validation."""

        def find_block_sum(start_idx):
            """Find sum of values in a block until empty row."""
            sum_vals = [0.0] * len(df.columns)
            count = 0
            i = start_idx + 1
            while i < len(df):
                row = df.iloc[i]
                if all(str(cell).strip() == "" for cell in row):
                    break
                for col in range(len(df.columns)):
                    val = df_numeric.iloc[i, col]
                    if not pd.isna(val):
                        sum_vals[col] += val
                count += 1
                i += 1
            return sum_vals, count, i

        def compare_sum_with_total(sum_vals, total_row, end_row):
            """Compare calculated sum with total row."""
            for col in range(len(df.columns)):
                total_val = total_row[col]
                if not pd.isna(total_val):
                    diff = sum_vals[col] - total_val
                    is_ok = abs(round(diff)) == 0
                    comment = f"Cột {
                        col +
                        1}: Tổng chi tiết = {
                        sum_vals[col]:,.2f}, Tổng trên bảng = {
                        total_val:,.2f}, Sai lệch = {
                        diff:,.0f}"
                    marks.append(
                        {
                            "row": end_row + 1,
                            "col": col,
                            "ok": is_ok,
                            "comment": None if is_ok else comment,
                        }
                    )
                    if not is_ok:
                        issues.append(comment)

        # Find start index (skip header rows)
        start_idx = 0
        while start_idx < len(df):
            row = df.iloc[start_idx]
            row_text = " ".join(str(x).lower() for x in row)
            if (
                all(str(cell).strip() == "" for cell in row)
                or "equity investments" in row_text
            ):
                break
            start_idx += 1

        # Find first block sum
        total1 = [0.0] * len(df.columns)
        sum1, count1, end1 = find_block_sum(start_idx)
        if count1 > 1 and end1 < len(df) - 1:
            total1_row = df_numeric.iloc[end1 + 1]
            compare_sum_with_total(sum1, total1_row, end1)
        total1 = sum1

        # Determine start for second block
        if count1 == 1:
            start_idx = end1 - 1
        else:
            start_idx = end1 + 1

        # Find second block if total_row_idx is after first block
        if total_row_idx > start_idx + 1:
            total2 = [0.0] * len(df.columns)
            sum2, count2, end2 = find_block_sum(start_idx)
            if count2 > 1 and end2 < len(df) - 1:
                total2_row = df_numeric.iloc[end2 + 1]
                compare_sum_with_total(sum2, total2_row, end2)

            # Handle special case for "revenue from" with negative values
            if "revenue from" in heading_lower:
                if total2_row.dropna().gt(0).all():
                    for col in range(len(df.columns)):
                        total2[col] = -sum2[col]
                else:
                    total2 = sum2
            else:
                total2 = sum2

            # Compare combined total with final row
            final_row = df_numeric.iloc[len(df) - 1]
            for col in range(len(df.columns)):
                combined = total1[col] + total2[col]
                final_val = final_row[col]
                if not pd.isna(final_val):
                    diff = combined - final_val
                    is_ok = abs(round(diff)) == 0
                    comment = f"Dòng Grand total - Cột {
                        col +
                        1}: Tổng cộng = {
                        combined:,.2f}, Dòng cuối = {
                        final_val:,.2f}, Sai lệch = {
                        diff:,.0f}"
                    marks.append(
                        {
                            "row": len(df) - 1,
                            "col": col,
                            "ok": is_ok,
                            "comment": None if is_ok else comment,
                        }
                    )
                    if not is_ok:
                        issues.append(comment)

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
                account_name = heading_lower
                if "accounts receivable from customers" in heading_lower:
                    account_name = "accounts receivable from customers"
                if account_name not in cross_check_marks:
                    CY_bal = (
                        df_numeric.iloc[end1 + 1, len(df.columns) - 2]
                        if not pd.isna(df_numeric.iloc[end1 + 1, len(df.columns) - 2])
                        else 0
                    )
                    PY_bal = (
                        df_numeric.iloc[end1 + 1, len(df.columns) - 1]
                        if not pd.isna(df_numeric.iloc[end1 + 1, len(df.columns) - 1])
                        else 0
                    )
                    self.cross_check_with_BSPL(
                        df,
                        cross_ref_marks,
                        issues,
                        account_name,
                        CY_bal,
                        PY_bal,
                        end1 + 1,
                        len(df.columns) - 2,
                        0,
                        -1,
                    )
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
        """Handle cross-check for FORM_1 tables (cross-ref at grand total)."""
        account_name = heading_lower
        if "accounts receivable from customers" in heading_lower:
            account_name = "accounts receivable from customers"
        if account_name not in cross_check_marks:
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
            cross_check_marks.add(account_name)

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
        """Handle cross-check for FORM_2 tables (cross-ref at both subtotal and grand total)."""
        # Cross-check at first subtotal
        account_name = heading_lower
        if account_name not in cross_check_marks:
            CY_bal = (
                df_numeric.iloc[end1 + 1, len(df.columns) - 2]
                if not pd.isna(df_numeric.iloc[end1 + 1, len(df.columns) - 2])
                else 0
            )
            PY_bal = (
                df_numeric.iloc[end1 + 1, len(df.columns) - 1]
                if not pd.isna(df_numeric.iloc[end1 + 1, len(df.columns) - 1])
                else 0
            )
            self.cross_check_with_BSPL(
                df,
                cross_ref_marks,
                issues,
                account_name,
                CY_bal,
                PY_bal,
                end1 + 1,
                len(df.columns) - 2,
                0,
                -1,
            )
            cross_check_marks.add(account_name)

        # Cross-check "revenue deductions"
        account_name = "revenue deductions"
        if account_name not in cross_check_marks:
            CY_bal = (
                df_numeric.iloc[end2 + 1, len(df.columns) - 2]
                if not pd.isna(df_numeric.iloc[end2 + 1, len(df.columns) - 2])
                else 0
            )
            PY_bal = (
                df_numeric.iloc[end2 + 1, len(df.columns) - 1]
                if not pd.isna(df_numeric.iloc[end2 + 1, len(df.columns) - 1])
                else 0
            )
            self.cross_check_with_BSPL(
                df,
                cross_ref_marks,
                issues,
                account_name,
                CY_bal,
                PY_bal,
                end2 + 1,
                len(df.columns) - 2,
                0,
                -1,
            )
            cross_check_marks.add(account_name)

        # Cross-check "net revenue (10 = 01 - 02)"
        account_name = "net revenue (10 = 01 - 02)"
        if account_name not in cross_check_marks:
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
            cross_check_marks.add(account_name)

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
            """Search for keyword in columns and cross-reference."""
            CY_col = 0
            PY_col = 0
            for j, row in df.iterrows():
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

            CY_bal = (
                0
                if pd.isna(df_numeric.iloc[total_row_xref, CY_col])
                else df_numeric.iloc[total_row_xref, CY_col]
            )
            PY_bal = (
                0
                if pd.isna(df_numeric.iloc[total_row_xref, PY_col])
                else df_numeric.iloc[total_row_xref, PY_col]
            )
            if CY_col != 0 or PY_col != 0:
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
            cross_check_marks.add(account_name)

        def search_row_and_cross_ref(account_name: str, col_xref: int):
            """Search for opening balance row and cross-reference."""
            CY_row = end1 + 1
            PY_row = 0
            for j, row in df.iterrows():
                row_text = " ".join(str(x).lower() for x in row)
                if "opening balance" in row_text:
                    PY_row = j
                    break

            CY_bal = (
                0
                if pd.isna(df_numeric.iloc[CY_row, col_xref])
                else df_numeric.iloc[CY_row, col_xref]
            )
            PY_bal = (
                0
                if pd.isna(df_numeric.iloc[PY_row, col_xref])
                else df_numeric.iloc[PY_row, col_xref]
            )
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
            cross_check_marks.add(account_name)

        # Handle special cases based on heading
        if heading_lower == "bad and doubtful debts":
            account_name = "allowance for doubtful debts"
            if account_name not in cross_check_marks:
                search_col_and_cross_ref("allowance", account_name, end1 + 1)

        elif heading_lower == "inventories":
            # Cross-ref costs
            account_name = "141"
            if account_name not in cross_check_marks:
                search_col_and_cross_ref("cost", account_name, end1 + 1)
            # Cross-ref allowance
            account_name = "149"
            if account_name not in cross_check_marks:
                search_col_and_cross_ref("allowance", account_name, end1 + 1)

        elif heading_lower in [
            "equity investments in other entity",
            "equity investments in other entities",
        ]:
            # Cross-ref costs or carrying amounts
            account_name = "investments in other entities"
            if account_name not in cross_check_marks:
                search_col_and_cross_ref("cost", account_name, end1 + 1)
                search_col_and_cross_ref("carrying amounts", account_name, end1 + 1)
            # Cross-ref allowance
            account_name = "254"
            if account_name not in cross_check_marks:
                search_col_and_cross_ref(
                    "allowance for diminution in value", account_name, end1 + 1
                )

        elif heading_lower == "construction in progress":
            account_name = heading_lower
            if account_name not in cross_check_marks:
                search_row_and_cross_ref(account_name, 1)

        elif heading_lower == "long-term prepaid expenses":
            account_name = heading_lower
            if account_name not in cross_check_marks:
                search_row_and_cross_ref(account_name, len(df.columns) - 1)

        elif "accounts payable to suppliers" in heading_lower:
            account_name = "accounts payable to suppliers"
            if account_name not in cross_check_marks:
                search_col_and_cross_ref("cost", account_name, end1 + 1)

        elif "taxes" in heading_lower:
            account_name = heading_lower
            if account_name not in cross_check_marks:
                CY_bal = (
                    df_numeric.iloc[end1 + 1, len(df.columns) - 1]
                    if not pd.isna(df_numeric.iloc[end1 + 1, len(df.columns) - 1])
                    else 0
                )
                PY_bal = (
                    df_numeric.iloc[end1 + 1, 1]
                    if not pd.isna(df_numeric.iloc[end1 + 1, 1])
                    else 0
                )
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
            if account_name not in cross_check_marks:
                search_col_and_cross_ref("carrying", account_name, end1 + 1)
