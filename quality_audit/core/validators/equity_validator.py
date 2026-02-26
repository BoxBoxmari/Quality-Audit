"""
Equity validator implementation.
"""

import logging
import re
from typing import Dict, List, Optional

import pandas as pd

from ...config.constants import EQUITY_TOLERANCE_REL
from ...config.feature_flags import get_feature_flags
from ...utils.numeric_utils import compare_amounts, normalize_numeric_column
from ...utils.row_classifier import RowClassifier, RowType
from .base_validator import BaseValidator, ValidationResult

logger = logging.getLogger(__name__)

# Keywords that suggest a row is a header row (equity statement)
_HEADER_KEYWORDS = (
    "total",
    "balance",
    "equity",
    "owners' equity",
    "capital",
    "movement",
    "share",
    "at beginning",
    "at end",
    "beginning",
    "end",
)

# Keywords that identify balance-at data rows (beginning/end of period)
BALANCE_AT_KEYWORDS = (
    "balance at",
    "opening balance",
    "closing balance",
    "số dư đầu",
    "số dư cuối",
    "cân đối đầu",
    "cân đối cuối",
)

# Distinguish opening vs closing for roll-forward: closing = opening + movements
OPENING_BALANCE_KEYWORDS = (
    "balance at beginning",
    "opening balance",
    "số dư đầu",
    "cân đối đầu",
    "balance at 1 jan",
)
CLOSING_BALANCE_KEYWORDS = (
    "balance at end",
    "closing balance",
    "số dư cuối",
    "cân đối cuối",
    "balance at 31 dec",
)


def _is_numeric_like(s: str) -> bool:
    """Return True if string looks like a number (including with NBSP/thousands)."""
    if not s or not str(s).strip():
        return False
    s = str(s).strip().replace("\u00a0", " ").replace(",", "")
    return bool(re.match(r"^[-+]?\d*\.?\d+([eE][-+]?\d+)?%?\s*$", s))


def _detect_header_row(df: pd.DataFrame) -> int:
    """
    Detect the last row index that belongs to the header block.
    Header-like rows: contain header keywords or have few numeric cells.
    """
    max_header_rows = min(10, max(1, len(df) - 1))
    last_header = 0
    for i in range(max_header_rows + 1):
        if i >= len(df):
            break
        row = df.iloc[i]
        row_text = " ".join(str(cell).lower() for cell in row if str(cell).strip())
        has_keyword = any(kw in row_text for kw in _HEADER_KEYWORDS)
        numeric_count = sum(1 for c in row if _is_numeric_like(str(c).strip()))
        n_cells = max(1, len(row))
        mostly_numeric = numeric_count / n_cells >= 0.5
        # Balance-at data rows (e.g. "Balance at beginning", "Balance at end") are data, not header
        balance_at_data = mostly_numeric and any(
            kw in row_text
            for kw in (
                "balance at beginning",
                "balance at end",
                "opening balance",
                "closing balance",
            )
        )
        if mostly_numeric and (not has_keyword or balance_at_data):
            break
        last_header = i
    return last_header


def _detect_first_data_row(df: pd.DataFrame) -> int:
    """First row index after the header block (data starts here)."""
    header_idx = _detect_header_row(df)
    return min(header_idx + 1, len(df))


def _collapsed_header_row(df: pd.DataFrame, header_idx: int) -> List[str]:
    """Build one label per column by collapsing rows 0..header_idx (multi-row header)."""
    ncols = df.shape[1]
    collapsed = []
    for j in range(ncols):
        parts = [
            str(df.iloc[i, j]).strip()
            for i in range(header_idx + 1)
            if str(df.iloc[i, j]).strip()
        ]
        collapsed.append(" ".join(parts) if parts else "")
    return collapsed


class EquityValidator(BaseValidator):
    """Validator for changes in owners' equity statement."""

    def validate(
        self,
        df: pd.DataFrame,
        heading: Optional[str] = None,
        table_context: Optional[Dict] = None,
    ) -> ValidationResult:
        """
        Validate changes in owners' equity table.

        Args:
            df: DataFrame containing equity data
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
            _, metadata = self._normalize_table_with_metadata(
                df, heading, table_context
            )
            df_numeric = df.astype(object).map(normalize_numeric_column)

            # Find "Balance at" / opening/closing balance rows
            balance_rows_idx = []
            for i in range(len(df)):
                row_text = " ".join(
                    str(cell).lower() for cell in df.iloc[i] if str(cell).strip()
                )
                if any(kw in row_text for kw in BALANCE_AT_KEYWORDS):
                    balance_rows_idx.append(i)

            balance_rows_idx = sorted(set(balance_rows_idx))

            # Classify each balance row as opening or closing for roll-forward
            opening_rows = []
            closing_rows = []
            for i in balance_rows_idx:
                row_text = " ".join(
                    str(cell).lower() for cell in df.iloc[i] if str(cell).strip()
                )
                is_opening = any(kw in row_text for kw in OPENING_BALANCE_KEYWORDS)
                is_closing = any(kw in row_text for kw in CLOSING_BALANCE_KEYWORDS)
                if is_opening and is_closing:
                    # Prefer opening if "1 jan" or "beginning" in text
                    if (
                        "1 jan" in row_text
                        or "beginning" in row_text
                        or "đầu" in row_text
                    ):
                        opening_rows.append(i)
                    else:
                        closing_rows.append(i)
                elif is_opening:
                    opening_rows.append(i)
                elif is_closing:
                    closing_rows.append(i)
                else:
                    if i == balance_rows_idx[0]:
                        opening_rows.append(i)
                    elif i == balance_rows_idx[-1]:
                        closing_rows.append(i)

            # Need at least one opening and one closing with opening < closing
            opening_idx = min(opening_rows) if opening_rows else None
            closing_idx = (
                min(c for c in closing_rows if opening_idx is None or c > opening_idx)
                if closing_rows
                else None
            )
            if opening_idx is None or closing_idx is None or opening_idx >= closing_idx:
                return ValidationResult(
                    status="INFO: Changes in owners' equity - không đủ dữ liệu 'Balance at' để kiểm tra",
                    marks=[],
                    cross_ref_marks=[],
                    rule_id="EQUITY_INSUFFICIENT_BALANCE_ROWS",
                    status_enum="INFO",
                    context={
                        "validator_type": "EquityValidator",
                        "total_row_method": "balance_at_keyword",
                        "balance_rows_found": len(balance_rows_idx),
                        "opening_rows": opening_rows,
                        "closing_rows": closing_rows,
                    },
                )

            flags = get_feature_flags()
            use_header_infer = flags.get("equity_header_infer", False)
            equity_no_evidence_not_fail = flags.get(
                "equity_no_evidence_not_fail", False
            )
            if use_header_infer:
                header_idx = _detect_header_row(df)
                first_data_idx = _detect_first_data_row(df)
            else:
                header_idx = 0
                first_data_idx = 1

            issues = []
            marks = []

            # Validate closing balance: closing = opening + sum(movements)
            # Ticket-4: Use RowClassifier to exclude SUBTOTAL/EMPTY/HEADER rows from sum
            idx2 = closing_idx
            movement_slice = df.iloc[opening_idx + 1 : closing_idx]
            movement_numeric_slice = df_numeric.iloc[opening_idx + 1 : closing_idx]
            if not movement_slice.empty:
                row_types = RowClassifier.classify_rows(movement_slice)
                data_mask = [rt in (RowType.DATA,) for rt in row_types]
                filtered_numeric = movement_numeric_slice[data_mask]
                movement_sum_series = filtered_numeric.sum(skipna=True)
            else:
                movement_sum_series = pd.Series(0.0, index=df_numeric.columns)
            expected_series_2 = df_numeric.iloc[opening_idx] + movement_sum_series
            actual_series_2 = df_numeric.iloc[idx2]

            for col in range(df.shape[1]):
                exp_val = expected_series_2.iloc[col]
                act_val = actual_series_2.iloc[col]
                is_ok = True
                comment = None
                no_evidence = False

                if not (pd.isna(exp_val) and pd.isna(act_val)):
                    exp_val = 0.0 if pd.isna(exp_val) else float(exp_val)
                    act_val = 0.0 if pd.isna(act_val) else float(act_val)
                    # Phase 5 B1: expected=0 and actual!=0 → no numeric evidence in slice; optionally not FAIL
                    no_evidence = (
                        equity_no_evidence_not_fail
                        and abs(exp_val) < 1e-6
                        and abs(act_val) > 1e-6
                    )
                    if no_evidence:
                        is_ok = True
                        comment = f"HÀNG: Balance at (thứ 2) - Cột {col + 1}: NO_EVIDENCE (tính=0, bảng={act_val:,.0f})"
                    else:
                        is_ok, abs_delta, rel_delta, tol_used = compare_amounts(
                            exp_val, act_val, rel_tol=EQUITY_TOLERANCE_REL
                        )
                        comment = None
                        if not is_ok:
                            comment = (
                                f"HÀNG: Balance at (thứ 2) - Cột {col + 1}: Tính={exp_val:,.0f}, Trên bảng={act_val:,.0f}, "
                                f"Δ={exp_val - act_val:,.0f}, |Δ|={abs_delta:,.2f}, rel%={rel_delta:.2f}%, tolerance={tol_used}"
                            )
                marks.append(
                    {
                        "row": idx2,
                        "col": col,
                        "ok": is_ok,
                        "comment": comment,
                    }
                )

                if not is_ok and not no_evidence:
                    issues.append(comment or "")

            # Validate third balance row if available
            if len(balance_rows_idx) >= 3:
                idx3 = balance_rows_idx[2]
                expected_series_3 = df_numeric.iloc[idx2:idx3].sum(skipna=True)
                actual_series_3 = df_numeric.iloc[idx3]

                for col in range(df.shape[1]):
                    exp_val = expected_series_3.iloc[col]
                    act_val = actual_series_3.iloc[col]
                    is_ok = True
                    comment = None
                    no_evidence = False

                    if not (pd.isna(exp_val) and pd.isna(act_val)):
                        exp_val = 0.0 if pd.isna(exp_val) else float(exp_val)
                        act_val = 0.0 if pd.isna(act_val) else float(act_val)
                        no_evidence = (
                            equity_no_evidence_not_fail
                            and abs(exp_val) < 1e-6
                            and abs(act_val) > 1e-6
                        )
                        if no_evidence:
                            is_ok = True
                            comment = f"HÀNG: Balance at (thứ 3) - Cột {col + 1}: NO_EVIDENCE (tính=0, bảng={act_val:,.0f})"
                        else:
                            is_ok, abs_delta, rel_delta, tol_used = compare_amounts(
                                exp_val, act_val, rel_tol=EQUITY_TOLERANCE_REL
                            )
                            comment = None
                            if not is_ok:
                                comment = (
                                    f"HÀNG: Balance at (thứ 3) - Cột {col + 1}: Tính={exp_val:,.0f}, Trên bảng={act_val:,.0f}, "
                                    f"Δ={exp_val - act_val:,.0f}, |Δ|={abs_delta:,.2f}, rel%={rel_delta:.2f}%, tolerance={tol_used}"
                                )
                    marks.append(
                        {
                            "row": idx3,
                            "col": col,
                            "ok": is_ok,
                            "comment": comment,
                        }
                    )

                    if not is_ok and not no_evidence:
                        issues.append(comment or "")

            # Validate column totals (multi-row header: collapse rows 0..header_idx)
            if use_header_infer and header_idx >= 0:
                collapsed = _collapsed_header_row(df, header_idx)
                header_norm = [x.strip().lower() for x in collapsed]
            else:
                header_row = df.iloc[header_idx].astype(str).tolist()
                header_norm = [str(x).strip().lower() for x in header_row]

            toe_idx = None
            total_idx = None

            for j, t in enumerate(header_norm):
                if toe_idx is None and "total owners' equity" in t:
                    toe_idx = j
                elif total_idx is None and len(t) < 15 and "total" in t:
                    total_idx = j

            # Fallback: "total equity" or "owners' equity" when "total owners' equity" not found
            if toe_idx is None:
                for j, t in enumerate(header_norm):
                    if "total equity" in t or ("owners' equity" in t and "total" in t):
                        toe_idx = j
                        break
            if toe_idx is None:
                for j, t in enumerate(header_norm):
                    if "owners' equity" in t:
                        toe_idx = j
                        break

            # Forensic logging for tbl_030 diagnosis (columns, toe_idx, left_part)
            if toe_idx is not None:
                cols = (
                    df.columns.tolist()
                    if hasattr(df.columns, "tolist")
                    else list(range(df.shape[1]))
                )
                left_cols = (
                    cols[:toe_idx]
                    if isinstance(cols[0], (int, str))
                    else list(range(toe_idx))
                )
                logger.info(
                    "EquityValidator tbl_030 forensics: columns=%s, toe_idx=%s, left_part_columns=%s",
                    cols,
                    toe_idx,
                    left_cols,
                )

            # Validate Total owners' equity column
            if toe_idx is not None and toe_idx > 0:
                fail_log_count = [0]  # use list to allow assignment in nested scope

                for r in range(first_data_idx, len(df)):
                    row = df_numeric.iloc[r]
                    left_part = row.iloc[:toe_idx]
                    expected = left_part.sum(skipna=True)
                    actual = row.iloc[toe_idx]

                    if not pd.isna(actual):
                        expected_f = 0.0 if pd.isna(expected) else float(expected)
                        actual_f = float(actual)
                        no_evidence = (
                            equity_no_evidence_not_fail
                            and abs(expected_f) < 1e-6
                            and abs(actual_f) > 1e-6
                        )
                        if no_evidence:
                            is_ok = True
                            comment = f"CỘT: Total owners' equity - Dòng {r + 1}: NO_EVIDENCE (tính=0, bảng={actual_f:,.0f})"
                        else:
                            is_ok, abs_delta, rel_delta, tol_used = compare_amounts(
                                expected_f, actual_f, rel_tol=EQUITY_TOLERANCE_REL
                            )
                            comment = None
                            if not is_ok:
                                diff = expected_f - actual_f
                                comment = (
                                    f"CỘT: Total owners' equity - Dòng {r + 1}: Tính={expected_f:,.0f}, Trên bảng={actual_f:,.0f}, "
                                    f"Sai lệch={diff:,.0f}, |Δ|={abs_delta:,.2f}, rel%={rel_delta:.2f}%, tolerance={tol_used}"
                                )
                        marks.append(
                            {
                                "row": r,
                                "col": toe_idx,
                                "ok": is_ok,
                                "comment": comment,
                            }
                        )

                        if not is_ok and not no_evidence:
                            issues.append(comment or "")
                            # Forensic: first 3 failing rows
                            if fail_log_count[0] < 3:
                                logger.info(
                                    "EquityValidator tbl_030 fail row %s: expected=%.4f actual=%.4f abs_delta=%.4f rel_pct=%.4f tolerance=%s",
                                    r + 1,
                                    expected_f,
                                    actual_f,
                                    abs_delta,
                                    rel_delta,
                                    tol_used,
                                )
                                fail_log_count[0] += 1

            # Generate status
            hard_issues = [m for m in issues if not m.startswith("INFO")]
            if not hard_issues:
                status = "PASS: Changes in owners' equity - kiểm tra công thức: KHỚP (0 sai lệch)"
            else:
                preview = "; ".join(issues[:10])
                more = f" ... (+{len(issues) - 10} dòng)" if len(issues) > 10 else ""
                status = f"FAIL: Changes in owners' equity - kiểm tra công thức: {len(hard_issues)} sai lệch. {preview}{more}"

            result = ValidationResult(
                status=status,
                marks=marks,
                cross_ref_marks=[],
                rule_id="EQUITY_FORMULA_CHECK",
                status_enum="PASS" if not hard_issues else "FAIL",
                context={
                    "validator_type": "EquityValidator",
                    "total_row_method": "balance_at_keyword",
                    "balance_rows_idx": balance_rows_idx,
                    "toe_idx": toe_idx,
                    "total_idx": total_idx,
                    **(metadata or {}),
                },
                assertions_count=len(marks),
            )
            result = self._enforce_pass_gating(
                result,
                result.assertions_count,
                (metadata or {}).get("numeric_evidence_score", 0.0),
            )
            return self._apply_warn_capping(result, table_context)
        except Exception as e:
            logger.exception(
                "EquityValidator failed with exception: %s", e, exc_info=True
            )
            return ValidationResult(
                status="FAIL_TOOL_LOGIC: Equity validator crashed",
                marks=[],
                cross_ref_marks=[],
                rule_id="FAIL_TOOL_LOGIC_VALIDATOR_CRASH",
                status_enum="FAIL_TOOL_LOGIC",
                context={
                    "validator_type": "EquityValidator",
                    "total_row_method": "balance_at_keyword",
                    **(dict(table_context) if table_context else {}),
                },
                exception_type=type(e).__name__,
                exception_message=str(e),
            )
        finally:
            self._current_table_context = {}
