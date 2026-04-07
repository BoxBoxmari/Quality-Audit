"""
Tax validator implementation.
"""

import logging
import re
from typing import Dict, List, Optional

import pandas as pd

from ...io.file_handler import get_validated_tax_rate
from ...utils.column_detector import ColumnDetector
from ...utils.numeric_utils import normalize_numeric_column
from .base_validator import BaseValidator, ValidationResult

logger = logging.getLogger(__name__)


class TaxValidator(BaseValidator):
    """Validator for tax reconciliation and effective tax rate tables."""

    def validate(
        self,
        df: pd.DataFrame,
        heading: Optional[str] = None,
        table_context: Optional[Dict] = None,
    ) -> ValidationResult:
        """
        Validate tax reconciliation table.

        Args:
            df: DataFrame containing tax data
            heading: Table heading
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

            # Check for empty DataFrame
            if df.empty:
                return ValidationResult(
                    status="INFO: Bảng trống",
                    marks=[],
                    cross_ref_marks=[],
                    status_enum="INFO",
                    rule_id="TABLE_EMPTY",
                )

            # C2: Try normalization first
            normalized_df, norm_metadata = self._normalize_table_with_metadata(
                df, heading_lower, table_context
            )

            # Use normalized DataFrame if available
            processed_df = normalized_df if normalized_df is not None else df

            if "reconciliation of effective tax rate" in heading_lower:
                result = self._validate_tax_reconciliation(processed_df, norm_metadata)
            else:
                result = self._validate_tax_remaining_tables(
                    processed_df, norm_metadata
                )
            return self._apply_warn_capping(result, table_context)
        except Exception as e:
            logger.exception("TaxValidator failed with exception: %s", e, exc_info=True)
            return ValidationResult(
                status="FAIL_TOOL_LOGIC: Tax validator crashed",
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

    def _validate_tax_reconciliation(
        self, df: pd.DataFrame, norm_metadata: Optional[Dict] = None
    ) -> ValidationResult:
        """Validate tax reconciliation table."""
        df_numeric = df.astype(object).map(normalize_numeric_column)

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
                or row_text.strip() == "accounting profit"
                or row_text.strip() == "accounting loss"
                or "accounting profit" in row_text
                or "accounting loss" in row_text
            ):
                profit_row_idx = i
                break

        if profit_row_idx is None:
            return ValidationResult(
                status="INFO: Không có dòng Accounting profit before tax hay Accounting loss before tax",
                marks=[],
                cross_ref_marks=[],
                status_enum="INFO",
                rule_id="TAX_NO_PROFIT_ROW",
            )

        issues: List[str] = []
        marks: List[Dict] = []
        cross_ref_marks: List[Dict] = []
        current_year_col, prior_year_col = (
            ColumnDetector.detect_financial_columns_advanced(df)
        )
        if current_year_col is None or prior_year_col is None:
            current_year_col = df.columns[-2]
            prior_year_col = df.columns[-1]
        current_year_idx = df.columns.get_loc(current_year_col)
        prior_year_idx = df.columns.get_loc(prior_year_col)

        # Cross-check accounting profit/(loss) before tax with BSPL
        current_year_balance = (
            0
            if pd.isna(df_numeric.iloc[profit_row_idx, current_year_idx])
            else df_numeric.iloc[profit_row_idx, current_year_idx]
        )
        prior_year_balance = (
            0
            if pd.isna(df_numeric.iloc[profit_row_idx, prior_year_idx])
            else df_numeric.iloc[profit_row_idx, prior_year_idx]
        )
        marks_set = self.context.marks if self.context else set()
        if account_name not in marks_set:
            self.cross_check_with_BSPL(
                df,
                cross_ref_marks,
                issues,
                account_name,
                current_year_balance,
                prior_year_balance,
                profit_row_idx,
                current_year_idx,
                0,
                -1,
            )
            marks_set.add(account_name)

        # Get tax rate from user
        # Get tax rate from user
        filename = self.context.current_filename if self.context else None
        tax_rate = get_validated_tax_rate(filename=filename, context=self.context)
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
                or "tax at rate" in row_text
                or "tax at statutory rate" in row_text
                or re.search(r"tax at .* tax rate", row_text, re.IGNORECASE)
            ):
                tax_rate_row_idx = i
                break

        if tax_rate_row_idx is not None:
            tax_row = df_numeric.iloc[tax_rate_row_idx]

            # P1-1: Infer tax rate từ bảng nếu có thể
            inferred_rate = None
            for col in range(len(df.columns)):
                profit_val = profit_row.iloc[col]
                tax_val = tax_row.iloc[col]
                if (
                    not pd.isna(profit_val)
                    and not pd.isna(tax_val)
                    and abs(profit_val) > 0.01
                ):
                    # Infer rate: tax / profit (handle sign, rounding)
                    inferred = abs(tax_val / profit_val)
                    if 0 <= inferred <= 1.0:  # Valid rate range
                        inferred_rate = inferred
                        break

            # Use inferred rate nếu có, else fallback to user input/default
            effective_rate = inferred_rate if inferred_rate is not None else tax_rate
            if inferred_rate is None:
                issues.append(
                    "WARN: Không thể infer tax rate từ bảng, dùng rate mặc định/user input"
                )

            # Validate tax calculation với effective_rate
            for col in range(len(df.columns)):
                profit_val = profit_row.iloc[col]
                tax_val = tax_row.iloc[col]

                if not pd.isna(profit_val) and not pd.isna(tax_val):
                    expected_tax = profit_val * effective_rate
                    diff = expected_tax - tax_val
                    is_ok = abs(round(diff)) == 0

                    rate_source = (
                        "inferred" if inferred_rate is not None else "default/user"
                    )
                    comment = (
                        f"Bước 1 - Cột {col + 1}: {effective_rate * 100}% lợi nhuận ({rate_source}) = {expected_tax:,.2f}, "
                        f"Thuế trên bảng = {tax_val:,.2f}, Sai lệch = {diff:,.2f}"
                    )

                    marks.append(
                        {
                            "row": tax_rate_row_idx,
                            "col": col,
                            "ok": is_ok,
                            "comment": comment,  # Always include for traceability
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

            # SCRUM-5/6: Bounds checking before iloc access
            if i < len(df) - 1 and i + 1 < len(df_numeric):
                total1_row = df_numeric.iloc[i + 1]
                for col in range(len(df.columns)):
                    total_val = total1_row.iloc[col]
                    if not pd.isna(total_val):
                        diff = sum1[col] - total_val
                        is_ok = abs(round(diff)) == 0
                        comment = (
                            f"Bước 2 - Cột {col + 1}: Tổng chi tiết = {sum1[col]:,.2f}, "
                            f"Tổng 1 = {total_val:,.2f}, Sai lệch = {diff:,.2f}"
                        )
                        marks.append(
                            {
                                "row": i + 1,
                                "col": col,
                                "ok": is_ok,
                                "comment": comment,  # Always include for traceability
                                "rule_id": "TAX_RATE_CALCULATION_STEP2",
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
                        total_val = total2_row.iloc[col]
                        if not pd.isna(total_val):
                            diff = sum2[col] - total_val
                            is_ok = abs(round(diff)) == 0
                            comment = (
                                f"Bước 3 - Cột {col + 1}: Tổng cộng dồn = {sum2[col]:,.2f}, "
                                f"Tổng 2 = {total_val:,.2f}, Sai lệch = {diff:,.2f}"
                            )
                            marks.append(
                                {
                                    "row": len(df) - 1,
                                    "col": col,
                                    "ok": is_ok,
                                    "comment": comment,  # Always include for traceability
                                    "rule_id": "TAX_RATE_CALCULATION_STEP3",
                                }
                            )
                            if not is_ok:
                                issues.append(comment)

            # Cross-check income tax at last row
            account_name = "income tax"
            current_year_balance = (
                0
                if pd.isna(df_numeric.iloc[len(df) - 1, current_year_idx])
                else df_numeric.iloc[len(df) - 1, current_year_idx]
            )
            prior_year_balance = (
                0
                if pd.isna(df_numeric.iloc[len(df) - 1, prior_year_idx])
                else df_numeric.iloc[len(df) - 1, prior_year_idx]
            )
            marks_set = self.context.marks if self.context else set()
            if account_name not in marks_set:
                self.cross_check_with_BSPL(
                    df,
                    cross_ref_marks,
                    issues,
                    account_name,
                    current_year_balance,
                    prior_year_balance,
                    len(df) - 1,
                    current_year_idx,
                    0,
                    -1,
                )
                marks_set.add(account_name)

        # Generate status
        if not issues:
            status = "PASS: Reconciliation of effective tax rate - kiểm tra công thức: KHỚP (0 sai lệch)"
        else:
            preview = "; ".join(issues[:10])
            more = f" ... (+{len(issues) - 10} dòng)" if len(issues) > 10 else ""
            status = (
                f"FAIL: Reconciliation of effective tax rate - kiểm tra công thức: {len(issues)} sai lệch. "
                f"{preview}{more}"
            )

        result = ValidationResult(
            status=status,
            marks=marks,
            cross_ref_marks=cross_ref_marks,
            assertions_count=len(marks) + len(cross_ref_marks),
        )
        result = self._enforce_pass_gating(
            result,
            result.assertions_count,
            (norm_metadata or {}).get("numeric_evidence_score", 0.0),
        )
        return result

    def _validate_tax_remaining_tables(
        self, df: pd.DataFrame, norm_metadata: Optional[Dict] = None
    ) -> ValidationResult:
        """Validate remaining tax-related tables (deferred tax assets/liabilities).
        Pattern E fix: Exclude all code-like columns from block sums and grand total.
        """
        # Multi-code exclusion: detect all code-like columns
        code_cols = self._detect_code_columns(df)
        note_col = (norm_metadata or {}).get("note_column") if norm_metadata else None
        if note_col is None:
            note_col = ColumnDetector.detect_note_column(df)
        exclude_for_totals = list(code_cols or []) + ([note_col] if note_col else [])
        exclude_for_totals_set = set(exclude_for_totals)
        if exclude_for_totals_set:
            df_numeric = self._convert_to_numeric_df_excluding_code(
                df, code_cols=exclude_for_totals
            )
            logger.debug(
                "TaxValidator remaining tables: Excluded code columns %s from normalization",
                code_cols,
            )
        else:
            df_numeric = df.astype(object).map(normalize_numeric_column)
        logger.info(
            "TaxValidator remaining tables: code_cols=%s",
            code_cols if code_cols else [],
        )
        issues = []
        marks = []

        def find_block_sum(start_idx, exclude_cols=None):
            """Find sum of values in a block until empty row. Skips all code columns."""
            exclude_cols = exclude_cols or set()
            sum_vals = [0.0] * len(df.columns)
            count = 0
            i = start_idx + 1
            while i < len(df):
                row = df.iloc[i]
                if all(str(cell).strip() == "" for cell in row):
                    break
                for col in range(len(df.columns)):
                    if df.columns[col] in exclude_cols:
                        continue
                    val = df_numeric.iloc[i, col]
                    if not pd.isna(val):
                        sum_vals[col] += val
                count += 1
                i += 1
            return sum_vals, count, i

        def compare_sum_with_total(sum_vals, total_row, end_row, exclude_cols=None):
            """Compare calculated sum with total row. Skips all code columns."""
            exclude_cols = exclude_cols or set()
            for col in range(len(df.columns)):
                if df.columns[col] in exclude_cols:
                    continue
                total_val = total_row.iloc[col]
                if not pd.isna(total_val):
                    diff = sum_vals[col] - total_val
                    is_ok = abs(round(diff)) == 0
                    comment = (
                        f"Cột {col + 1}: Tổng chi tiết = {sum_vals[col]:,.2f}, "
                        f"Tổng trên bảng = {total_val:,.2f}, Sai lệch = {diff:,.0f}"
                    )
                    marks.append(
                        {
                            "row": end_row + 1,
                            "col": col,
                            "ok": is_ok,
                            "comment": comment,  # Always include for traceability
                        }
                    )
                    if not is_ok:
                        issues.append(comment)

        # Find total row (exclude code + note columns from total-row detection)
        total_row_idx = self._find_total_row(df, code_cols=exclude_for_totals)
        if total_row_idx is None:
            return ValidationResult(
                status="INFO: Bảng không có dòng tổng",
                marks=[],
                cross_ref_marks=[],
                status_enum="INFO",
                rule_id="TABLE_NO_TOTAL_ROW",
                context={"excluded_columns": exclude_for_totals},
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

        # Validate block sums (Pattern E: exclude code + note columns)
        sum1, count1, end1 = find_block_sum(
            start_idx, exclude_cols=exclude_for_totals_set
        )
        if count1 > 1 and end1 < len(df) - 1 and end1 + 1 < len(df_numeric):
            total1_row = df_numeric.iloc[end1 + 1]
            compare_sum_with_total(
                sum1, total1_row, end1, exclude_cols=exclude_for_totals_set
            )

        # Check for second block if total_row_idx is after first block
        if total_row_idx > end1 + 1:
            start_idx = end1 - 1 if count1 == 1 else end1 + 1

            sum2, count2, end2 = find_block_sum(
                start_idx, exclude_cols=exclude_for_totals_set
            )
            if count2 > 1 and end2 < len(df) - 1 and end2 + 1 < len(df_numeric):
                total2_row = df_numeric.iloc[end2 + 1]
                compare_sum_with_total(
                    sum2, total2_row, end2, exclude_cols=exclude_for_totals_set
                )

            # Compare combined total with final row (skip code + note columns)
            # SCRUM-5/6: Bounds checking before iloc access
            if len(df_numeric) > 0:
                final_row = df_numeric.iloc[len(df) - 1]
                for col in range(len(df.columns)):
                    if df.columns[col] in exclude_for_totals_set:
                        continue
                    combined = sum1[col] + sum2[col]
                    final_val = final_row.iloc[col]
                    if not pd.isna(final_val):
                        diff = combined - final_val
                        is_ok = abs(round(diff)) == 0
                        comment = (
                            f"Dòng Grand total - Cột {col + 1}: Tổng cộng = {combined:,.2f}, "
                            f"Dòng cuối = {final_val:,.2f}, Sai lệch = {diff:,.0f}"
                        )
                        marks.append(
                            {
                                "row": len(df) - 1,
                                "col": col,
                                "ok": is_ok,
                                "comment": comment,  # Always include for traceability
                                "rule_id": "TAX_REMAINING_TABLE_GRAND_TOTAL",
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

        result = ValidationResult(
            status=status,
            marks=marks,
            cross_ref_marks=[],
            context={"excluded_columns": list(code_cols) if code_cols else []},
            assertions_count=len(marks),
        )
        result = self._enforce_pass_gating(
            result,
            result.assertions_count,
            (norm_metadata or {}).get("numeric_evidence_score", 0.0),
        )
        return result
