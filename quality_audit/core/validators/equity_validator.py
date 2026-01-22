"""
Equity validator implementation.
"""

import pandas as pd

from ...utils.numeric_utils import normalize_numeric_column
from .base_validator import BaseValidator, ValidationResult


class EquityValidator(BaseValidator):
    """Validator for changes in owners' equity statement."""

    def validate(self, df: pd.DataFrame, heading: str = None) -> ValidationResult:
        """
        Validate changes in owners' equity table.

        Args:
            df: DataFrame containing equity data
            heading: Table heading (unused)

        Returns:
            ValidationResult: Validation results
        """
        df_numeric = df.map(normalize_numeric_column)

        # Find "Balance at" rows
        balance_rows_idx = []
        for i in range(len(df)):
            row_text = " ".join(
                str(cell).lower() for cell in df.iloc[i] if str(cell).strip()
            )
            if "balance at" in row_text:
                balance_rows_idx.append(i)

        balance_rows_idx = sorted(set(balance_rows_idx))

        # Need at least 2 balance rows for validation
        if len(balance_rows_idx) < 2:
            return ValidationResult(
                status="INFO: Changes in owners' equity - không đủ dữ liệu 'Balance at' để kiểm tra",
                marks=[],
                cross_ref_marks=[],
            )

        header_idx = 0
        first_data_idx = 1

        issues = []
        marks = []

        # Validate second balance row
        if len(balance_rows_idx) >= 2:
            idx2 = balance_rows_idx[1]
            expected_series_2 = df_numeric.iloc[first_data_idx:idx2].sum(skipna=True)
            actual_series_2 = df_numeric.iloc[idx2]

            for col in range(df.shape[1]):
                exp_val = expected_series_2.iloc[col]
                act_val = actual_series_2.iloc[col]

                if not (pd.isna(exp_val) and pd.isna(act_val)):
                    exp_val = 0.0 if pd.isna(exp_val) else float(exp_val)
                    act_val = 0.0 if pd.isna(act_val) else float(act_val)
                    diff = exp_val - act_val
                    is_ok = abs(diff) < 0.01

                    comment = f"HÀNG: Balance at (thứ 2) - Cột {
                        col +
                        1}: Tính={
                        exp_val:,.0f}, Trên bảng={
                        act_val:,.0f}, Δ={
                        diff:,.0f}"
                    marks.append(
                        {
                            "row": idx2,
                            "col": col,
                            "ok": is_ok,
                            "comment": None if is_ok else comment,
                        }
                    )

                    if not is_ok:
                        issues.append(comment)

        # Validate third balance row if available
        if len(balance_rows_idx) >= 3:
            idx3 = balance_rows_idx[2]
            expected_series_3 = df_numeric.iloc[idx2:idx3].sum(skipna=True)
            actual_series_3 = df_numeric.iloc[idx3]

            for col in range(df.shape[1]):
                exp_val = expected_series_3.iloc[col]
                act_val = actual_series_3.iloc[col]

                if not (pd.isna(exp_val) and pd.isna(act_val)):
                    exp_val = 0.0 if pd.isna(exp_val) else float(exp_val)
                    act_val = 0.0 if pd.isna(act_val) else float(act_val)
                    diff = exp_val - act_val
                    is_ok = abs(diff) < 0.01

                    comment = f"HÀNG: Balance at (thứ 3) - Cột {
                        col +
                        1}: Tính={
                        exp_val:,.0f}, Trên bảng={
                        act_val:,.0f}, Δ={
                        diff:,.0f}"
                    marks.append(
                        {
                            "row": idx3,
                            "col": col,
                            "ok": is_ok,
                            "comment": None if is_ok else comment,
                        }
                    )

                    if not is_ok:
                        issues.append(comment)

        # Validate column totals
        header_row = df.iloc[header_idx].astype(str).tolist()
        header_norm = [str(x).strip().lower() for x in header_row]

        toe_idx = None
        total_idx = None

        for j, t in enumerate(header_norm):
            if toe_idx is None and "total owners' equity" in t:
                toe_idx = j
            elif total_idx is None and len(t) < 15 and "total" in t:
                total_idx = j

        # Validate Total owners' equity column
        if toe_idx is not None and toe_idx > 0:
            for r in range(first_data_idx, len(df)):
                row = df_numeric.iloc[r]
                left_part = row.iloc[:toe_idx]
                expected = left_part.sum(skipna=True)
                actual = row.iloc[toe_idx]

                if not pd.isna(actual):
                    expected = 0.0 if pd.isna(expected) else float(expected)
                    actual = float(actual)
                    diff = expected - actual
                    is_ok = abs(diff) < 0.01

                    comment = f"CỘT: Total owners' equity - Dòng {
                        r +
                        1}: Tính={
                        expected:,.0f}, Trên bảng={
                        actual:,.0f}, Sai lệch={
                        diff:,.0f}"
                    marks.append(
                        {
                            "row": r,
                            "col": toe_idx,
                            "ok": is_ok,
                            "comment": None if is_ok else comment,
                        }
                    )

                    if not is_ok:
                        issues.append(comment)

        # Generate status
        hard_issues = [m for m in issues if not m.startswith("INFO")]
        if not hard_issues:
            status = "PASS: Changes in owners' equity - kiểm tra công thức: KHỚP (0 sai lệch)"
        else:
            preview = "; ".join(issues[:10])
            more = f" ... (+{len(issues) - 10} dòng)" if len(issues) > 10 else ""
            status = f"FAIL: Changes in owners' equity - kiểm tra công thức: {
                len(hard_issues)} sai lệch. {preview}{more}"

        return ValidationResult(status=status, marks=marks, cross_ref_marks=[])
