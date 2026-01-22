"""
Tax validator implementation.
"""

import pandas as pd

from ...io.file_handler import get_validated_tax_rate
from ...utils.numeric_utils import normalize_numeric_column
from ..cache_manager import cross_check_marks
from .base_validator import BaseValidator, ValidationResult


class TaxValidator(BaseValidator):
    """Validator for tax reconciliation and effective tax rate tables."""

    def validate(self, df: pd.DataFrame, heading: str = None) -> ValidationResult:
        """
        Validate tax reconciliation table.

        Args:
            df: DataFrame containing tax data
            heading: Table heading

        Returns:
            ValidationResult: Validation results
        """
        heading_lower = heading.lower().strip() if heading else ""

        if "reconciliation of effective tax rate" in heading_lower:
            return self._validate_tax_reconciliation(df)
        else:
            return self._validate_tax_remaining_tables(df)

    def _validate_tax_reconciliation(self, df: pd.DataFrame) -> ValidationResult:
        """Validate tax reconciliation table."""
        df_numeric = df.map(normalize_numeric_column)

        # Find profit row
        profit_row_idx = None
        account_name = "50"
        for i, row in df.iterrows():
            row_text = " ".join(str(cell).lower() for cell in row)
            if (
                "accounting profit before tax" in row_text
                or "accounting loss before tax" in row_text
                or "accounting profit/(loss) before tax" in row_text
                or "accounting (loss)/profit before tax" in row_text
            ):
                profit_row_idx = i
                break

        if profit_row_idx is None:
            return ValidationResult(
                status="INFO: Không có dòng Accounting profit before tax hay Accounting loss before tax",
                marks=[],
                cross_ref_marks=[],
            )

        issues = []
        marks = []
        cross_ref_marks = []

        # Cross-check accounting profit/(loss) before tax with BSPL
        CY_bal = (
            0
            if pd.isna(df_numeric.iloc[profit_row_idx, len(df.columns) - 2])
            else df_numeric.iloc[profit_row_idx, len(df.columns) - 2]
        )
        PY_bal = (
            0
            if pd.isna(df_numeric.iloc[profit_row_idx, len(df.columns) - 1])
            else df_numeric.iloc[profit_row_idx, len(df.columns) - 1]
        )
        if account_name not in cross_check_marks:
            self.cross_check_with_BSPL(
                df,
                cross_ref_marks,
                issues,
                account_name,
                CY_bal,
                PY_bal,
                profit_row_idx,
                len(df.columns) - 2,
                0,
                -1,
            )
            cross_check_marks.add(account_name)

        # Get tax rate from user
        tax_rate = get_validated_tax_rate()
        if tax_rate is None:
            return ValidationResult(
                status="WARN: Không thể đọc thuế suất từ người dùng",
                marks=[],
                cross_ref_marks=cross_ref_marks,
            )

        # Find tax rate row
        profit_row = df_numeric.iloc[profit_row_idx]
        tax_rate_row_idx = None

        for i in range(profit_row_idx + 1, len(df)):
            row_text = " ".join(str(cell).lower() for cell in df.iloc[i])
            if (
                "tax at the company's tax rate" in row_text
                or "tax at the group's tax rate" in row_text
            ):
                tax_rate_row_idx = i
                break

        if tax_rate_row_idx is not None:
            tax_row = df_numeric.iloc[tax_rate_row_idx]

            # Validate tax calculation
            for col in range(len(df.columns)):
                profit_val = profit_row[col]
                tax_val = tax_row[col]

                if not pd.isna(profit_val) and not pd.isna(tax_val):
                    expected_tax = profit_val * tax_rate
                    diff = expected_tax - tax_val
                    is_ok = abs(round(diff)) == 0

                    comment = (
                        f"Bước 1 - Cột {col +
                                        1}: {tax_rate *
                                             100}% lợi nhuận = {expected_tax:,.2f}, "
                        f"Thuế trên bảng = {tax_val:,.2f}, Sai lệch = {diff:,.2f}"
                    )

                    marks.append(
                        {
                            "row": tax_rate_row_idx,
                            "col": col,
                            "ok": is_ok,
                            "comment": None if is_ok else comment,
                        }
                    )

                    if not is_ok:
                        issues.append(comment)

            # Bước 2: Cộng dồn từ dòng sau dòng thuế đến dòng trống
            sum1 = [0.0] * len(df.columns)
            i = tax_rate_row_idx
            while i < len(df):
                row = df.iloc[i]
                if all(str(cell).strip() == "" for cell in row):
                    break
                for col in range(len(df.columns)):
                    val = df_numeric.iloc[i, col]
                    if not pd.isna(val):
                        sum1[col] += val
                i += 1

            if i < len(df) - 1:
                total1_row = df_numeric.iloc[i + 1]
                for col in range(len(df.columns)):
                    total_val = total1_row[col]
                    if not pd.isna(total_val):
                        diff = sum1[col] - total_val
                        is_ok = abs(round(diff)) == 0
                        comment = f"Bước 2 - Cột {
                            col +
                            1}: Tổng chi tiết = {
                            sum1[col]:,.2f}, Tổng 1 = {
                            total_val:,.2f}, Sai lệch = {
                            diff:,.2f}"
                        marks.append(
                            {
                                "row": i + 1,
                                "col": col,
                                "ok": is_ok,
                                "comment": None if is_ok else comment,
                            }
                        )
                        if not is_ok:
                            issues.append(comment)

                # Bước 3: Cộng tiếp các dòng sau nếu có số liệu
                sum2 = sum1.copy()
                j = i + 2
                while j < len(df) - 1:
                    row = df.iloc[j]
                    if all(str(cell).strip() == "" for cell in row):
                        break
                    for col in range(len(df.columns)):
                        val = df_numeric.iloc[j, col]
                        if not pd.isna(val):
                            sum2[col] += val
                    j += 1

                if j < len(df):
                    total2_row = df_numeric.iloc[len(df) - 1]
                    for col in range(len(df.columns)):
                        total_val = total2_row[col]
                        if not pd.isna(total_val):
                            diff = sum2[col] - total_val
                            is_ok = abs(round(diff)) == 0
                            comment = f"Bước 3 - Cột {
                                col +
                                1}: Tổng cộng dồn = {
                                sum2[col]:,.2f}, Tổng 2 = {
                                total_val:,.2f}, Sai lệch = {
                                diff:,.2f}"
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

            # Cross-check income tax at last row
            account_name = "income tax"
            CY_bal = (
                0
                if pd.isna(df_numeric.iloc[len(df) - 1, len(df.columns) - 2])
                else df_numeric.iloc[len(df) - 1, len(df.columns) - 2]
            )
            PY_bal = (
                0
                if pd.isna(df_numeric.iloc[len(df) - 1, len(df.columns) - 1])
                else df_numeric.iloc[len(df) - 1, len(df.columns) - 1]
            )
            if account_name not in cross_check_marks:
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

        # Generate status
        if not issues:
            status = "PASS: Reconciliation of effective tax rate - kiểm tra công thức: KHỚP (0 sai lệch)"
        else:
            preview = "; ".join(issues[:10])
            more = f" ... (+{len(issues) - 10} dòng)" if len(issues) > 10 else ""
            status = f"FAIL: Reconciliation of effective tax rate - kiểm tra công thức: {
                len(issues)} sai lệch. {preview}{more}"

        return ValidationResult(
            status=status, marks=marks, cross_ref_marks=cross_ref_marks
        )

    def _validate_tax_remaining_tables(self, df: pd.DataFrame) -> ValidationResult:
        """Validate remaining tax-related tables (deferred tax assets/liabilities)."""
        df_numeric = df.map(normalize_numeric_column)
        issues = []
        marks = []

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

        # Find total row
        total_row_idx = self._find_total_row(df)
        if total_row_idx is None:
            return ValidationResult(
                status="INFO: Bảng không có dòng tổng", marks=[], cross_ref_marks=[]
            )

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

        # Validate block sums
        sum1, count1, end1 = find_block_sum(start_idx)
        if count1 > 1 and end1 < len(df) - 1:
            total1_row = df_numeric.iloc[end1 + 1]
            compare_sum_with_total(sum1, total1_row, end1)

        # Check for second block if total_row_idx is after first block
        if total_row_idx > end1 + 1:
            if count1 == 1:
                start_idx = end1 - 1
            else:
                start_idx = end1 + 1

            sum2, count2, end2 = find_block_sum(start_idx)
            if count2 > 1 and end2 < len(df) - 1:
                total2_row = df_numeric.iloc[end2 + 1]
                compare_sum_with_total(sum2, total2_row, end2)

            # Compare combined total with final row
            final_row = df_numeric.iloc[len(df) - 1]
            for col in range(len(df.columns)):
                combined = sum1[col] + sum2[col]
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

        # Generate status
        if not issues:
            status = "PASS: Kiểm tra công thức: KHỚP (0 sai lệch)"
        else:
            preview = "; ".join(issues[:10])
            more = f" ... (+{len(issues) - 10} dòng)" if len(issues) > 10 else ""
            status = (
                f"FAIL: Kiểm tra công thức: {len(issues)} sai lệch. {preview}{more}"
            )

        return ValidationResult(status=status, marks=marks, cross_ref_marks=[])
