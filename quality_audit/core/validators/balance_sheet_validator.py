"""
Balance Sheet validator implementation.
"""

from typing import Dict, List, Tuple

import pandas as pd

from ...config.validation_rules import get_balance_rules
from ...utils.chunk_processor import ChunkProcessor
from ...utils.column_detector import ColumnDetector
from ...utils.numeric_utils import parse_numeric
from ..cache_manager import cross_check_cache
from .base_validator import BaseValidator, ValidationResult


class BalanceSheetValidator(BaseValidator):
    """Validator for balance sheet financial statements."""

    LARGE_TABLE_THRESHOLD = 1000  # Rows threshold for chunked processing

    def _validate_balance_sheet_vectorized(
        self,
        data: Dict[str, Tuple[float, float]],
        code_rowpos: Dict[str, int],
        cur_col: str,
        prior_col: str,
        header: List[str],
        header_idx: int,
        rules: Dict,
    ) -> tuple:
        """
        Vectorized balance sheet validation using pandas operations.

        This method uses vectorized operations for rule validation to improve
        performance on large datasets.

        Args:
            data: Dictionary mapping normalized codes to (cy_value, py_value) tuples
            code_rowpos: Dictionary mapping codes to row positions
            cur_col: Name of current year column
            prior_col: Name of prior year column
            header: List of header column names
            header_idx: Index of header row in original DataFrame
            rules: Dictionary of parent-child validation rules

        Returns:
            Tuple of (issues list, marks list)
        """
        # Get column positions
        try:
            cur_col_pos = header.index(cur_col)
            prior_col_pos = header.index(prior_col)
        except ValueError:
            cur_col_pos = len(header) - 2
            prior_col_pos = len(header) - 1

        # Convert data dict to DataFrame for vectorized operations
        if not data:
            return [], []

        # Convert Dict[str, Tuple[float, float]] to DataFrame
        records = []
        for code, (cy_val, py_val) in data.items():
            records.append({"code": code, "cy_balance": cy_val, "py_balance": py_val})
        data_df = pd.DataFrame(records)

        issues = []
        marks = []

        # Vectorized rule validation
        for parent, children in rules.items():
            parent_norm = self._normalize_code(parent)
            if parent_norm not in data:
                continue

            # Vectorized child code lookup using pandas isin
            child_norms = [self._normalize_code(ch) for ch in children]
            child_mask = data_df["code"].isin(child_norms)
            child_data = data_df[child_mask]

            if child_data.empty:
                continue

            # Vectorized sum calculation
            child_sum_cy = child_data["cy_balance"].sum()
            child_sum_py = child_data["py_balance"].sum()

            parent_row = data_df[data_df["code"] == parent_norm]
            if parent_row.empty:
                continue

            parent_cy = parent_row["cy_balance"].iloc[0]
            parent_py = parent_row["py_balance"].iloc[0]

            # Calculate differences
            diff_cy = child_sum_cy - parent_cy
            diff_py = child_sum_py - parent_py
            is_ok_cy = abs(diff_cy) < 0.01
            is_ok_py = abs(diff_py) < 0.01

            # Find missing children using vectorized operations
            all_child_codes = set(child_norms)
            existing_codes = set(data_df["code"].unique())
            missing = list(all_child_codes - existing_codes)

            # Create marks
            if parent_norm in code_rowpos:
                df_row = header_idx + 1 + code_rowpos[parent_norm]
                comment = (
                    f"{parent_norm} = sum({','.join(children)}); "
                    f"Tính={child_sum_cy:,.0f}/{child_sum_py:,.0f}; "
                    f"Thực tế={parent_cy:,.0f}/{parent_py:,.0f}; "
                    f"Δ={diff_cy:,.0f}/{diff_py:,.0f}"
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

        return issues, marks

    def validate(self, df: pd.DataFrame, heading: str = None) -> ValidationResult:
        """
        Validate balance sheet table with automatic chunked processing for large tables.

        Args:
            df: DataFrame containing balance sheet data
            heading: Table heading (unused for balance sheet)

        Returns:
            ValidationResult: Validation results
        """
        # Find header row
        header_idx = self._find_header_row(df, "code")
        if header_idx is None:
            return ValidationResult(
                status="WARN: Balance sheet - không tìm thấy cột 'Code' để kiểm tra",
                marks=[],
                cross_ref_marks=[],
            )

        # Extract data with proper headers
        header = [str(c).strip() for c in df.iloc[header_idx].tolist()]
        tmp = df.iloc[header_idx + 1:].copy()
        tmp.columns = header

        # Check if table is large enough to use chunked processing
        if len(tmp) > self.LARGE_TABLE_THRESHOLD:
            return self._validate_large_table_chunked(tmp, header, header_idx, heading)
        else:
            return self._validate_standard(tmp, header, header_idx, heading)

    def _validate_standard(
        self, tmp: pd.DataFrame, header: List[str], header_idx: int, heading: str = None
    ) -> ValidationResult:
        """
        Validate standard-sized balance sheet table (non-chunked).

        Args:
            tmp: DataFrame with proper headers (data rows only, no header row)
            header: List of header column names
            header_idx: Index of header row in original DataFrame
            heading: Table heading (unused)

        Returns:
            ValidationResult: Validation results
        """

        # Identify columns
        code_col = next(
            (c for c in tmp.columns if str(c).strip().lower() == "code"), None
        )
        if code_col is None:
            return ValidationResult(
                status="WARN: Balance sheet - không xác định được cột 'Code'",
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

        # Vectorized data extraction and cache operations
        # Normalize codes using vectorized operations
        tmp["_normalized_code"] = tmp[code_col].apply(self._normalize_code)

        # Filter valid codes
        valid_code_mask = tmp["_normalized_code"].str.match(r"^[0-9]+[A-Z]?$", na=False)
        valid_rows = tmp[valid_code_mask].copy()

        if valid_rows.empty:
            return ValidationResult(
                status="WARN: Balance sheet - không tìm thấy mã tài khoản hợp lệ",
                marks=[],
                cross_ref_marks=[],
            )

        # Vectorized numeric conversion
        valid_rows["_cy_val"] = valid_rows[cur_col].apply(parse_numeric)
        valid_rows["_py_val"] = valid_rows[prior_col].apply(parse_numeric)

        # Build data map for cache operations (still needed for cross-checking)
        data = {}
        code_rowpos = {}

        # Process rows for cache operations (this part still needs iteration for
        # cache logic)
        for ridx, row in valid_rows.iterrows():
            code = row["_normalized_code"]
            cur_val = row["_cy_val"]
            prior_val = row["_py_val"]

            # Handle code conflicts (prefer non-zero values)
            if code in data:
                old_cur, old_pr = data[code]
                if (
                    abs(cur_val) + abs(prior_val) == 0
                    and abs(old_cur) + abs(old_pr) != 0
                ):
                    continue

            data[code] = (cur_val, prior_val)

            # Cross-check cache for notes
            if note_col and row.get(note_col, "") != "":
                acc_name = row.get(tmp.columns[0], "").strip().lower()
                if acc_name:
                    cross_check_cache.set(acc_name, (cur_val, prior_val))
            elif code in ["141", "149", "251", "252", "253", "254"]:
                if code in ["251", "252", "253"]:
                    try:
                        old_cur, old_pr = cross_check_cache.get(
                            "investments in other entities"
                        ) or (0.0, 0.0)
                        cross_check_cache.set(
                            "investments in other entities",
                            (cur_val + old_cur, prior_val + old_pr),
                        )
                    except Exception:
                        pass
                cross_check_cache.set(code, (cur_val, prior_val))

            code_rowpos[code] = ridx - tmp.index[0]

        # Get column positions for marking
        try:
            cur_col_pos = header.index(cur_col)
            prior_col_pos = header.index(prior_col)
        except ValueError:
            cur_col_pos = len(header) - 2
            prior_col_pos = len(header) - 1

        # Use vectorized validation for rules
        rules = get_balance_rules()
        issues, marks = self._validate_balance_sheet_vectorized(
            data, code_rowpos, cur_col, prior_col, header, header_idx, rules
        )

        # Generate status
        if not issues:
            status = "PASS: Balance sheet - kiểm tra công thức: KHỚP (0 sai lệch)"
        else:
            preview = "; ".join(issues[:10])
            more = f" ... (+{len(issues) - 10} dòng)" if len(issues) > 10 else ""
            status = f"FAIL: Balance sheet - kiểm tra công thức: {
                len(issues)} sai lệch. {preview}{more}"

        return ValidationResult(status=status, marks=marks, cross_ref_marks=[])

    def _validate_large_table_chunked(
        self, tmp: pd.DataFrame, header: List[str], header_idx: int, heading: str = None
    ) -> ValidationResult:
        """
        Validate large balance sheet table using chunked processing.

        Processes the table in chunks to manage memory, then aggregates results
        for final validation.

        Args:
            tmp: DataFrame with proper headers (data rows only, no header row)
            header: List of header column names
            header_idx: Index of header row in original DataFrame
            heading: Table heading (unused)

        Returns:
            ValidationResult: Validation results
        """
        # Identify columns (same as standard validation)
        code_col = next(
            (c for c in tmp.columns if str(c).strip().lower() == "code"), None
        )
        if code_col is None:
            return ValidationResult(
                status="WARN: Balance sheet - không xác định được cột 'Code'",
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

        # Process in chunks to extract data
        chunk_size = self.LARGE_TABLE_THRESHOLD
        data = {}
        code_rowpos = {}
        base_index = tmp.index[0]  # Store base index for row position calculation

        def process_chunk(chunk: pd.DataFrame) -> Dict:
            """Process a single chunk to extract data."""
            chunk_data = {}
            chunk_code_rowpos = {}

            # Normalize codes
            chunk["_normalized_code"] = chunk[code_col].apply(self._normalize_code)

            # Filter valid codes
            valid_code_mask = chunk["_normalized_code"].str.match(
                r"^[0-9]+[A-Z]?$", na=False
            )
            valid_rows = chunk[valid_code_mask].copy()

            if valid_rows.empty:
                return {"data": {}, "code_rowpos": {}}

            # Vectorized numeric conversion
            valid_rows["_cy_val"] = valid_rows[cur_col].apply(parse_numeric)
            valid_rows["_py_val"] = valid_rows[prior_col].apply(parse_numeric)

            # Process rows for cache operations
            for ridx, row in valid_rows.iterrows():
                code = row["_normalized_code"]
                cur_val = row["_cy_val"]
                prior_val = row["_py_val"]

                # Handle code conflicts (prefer non-zero values)
                if code in chunk_data:
                    old_cur, old_pr = chunk_data[code]
                    if (
                        abs(cur_val) + abs(prior_val) == 0
                        and abs(old_cur) + abs(old_pr) != 0
                    ):
                        continue

                chunk_data[code] = (cur_val, prior_val)

                # Cross-check cache for notes
                if note_col and row.get(note_col, "") != "":
                    acc_name = row.get(tmp.columns[0], "").strip().lower()
                    if acc_name:
                        cross_check_cache.set(acc_name, (cur_val, prior_val))
                elif code in ["141", "149", "251", "252", "253", "254"]:
                    if code in ["251", "252", "253"]:
                        try:
                            old_cur, old_pr = cross_check_cache.get(
                                "investments in other entities"
                            ) or (0.0, 0.0)
                            cross_check_cache.set(
                                "investments in other entities",
                                (cur_val + old_cur, prior_val + old_pr),
                            )
                        except Exception:
                            pass
                    cross_check_cache.set(code, (cur_val, prior_val))

                # Calculate row position relative to original DataFrame
                chunk_code_rowpos[code] = ridx - base_index

            return {"data": chunk_data, "code_rowpos": chunk_code_rowpos}

        # Process chunks with memory management
        chunk_results = ChunkProcessor.process_with_memory_limits(
            tmp, process_chunk, chunk_size=chunk_size, enable_gc=True
        )

        # Aggregate data from all chunks
        for chunk_result in chunk_results:
            if isinstance(chunk_result, dict) and "data" in chunk_result:
                chunk_data = chunk_result["data"]
                chunk_code_rowpos = chunk_result["code_rowpos"]

                # Merge chunk data into main data dict (handle conflicts)
                for code, (cy_val, py_val) in chunk_data.items():
                    if code in data:
                        # Prefer non-zero values
                        old_cy, old_py = data[code]
                        if (
                            abs(cy_val) + abs(py_val) == 0
                            and abs(old_cy) + abs(old_py) != 0
                        ):
                            continue
                    data[code] = (cy_val, py_val)
                    # Update row position (keep first occurrence or latest, depending on
                    # logic)
                    if code not in code_rowpos or abs(cy_val) + abs(py_val) > abs(
                        data[code][0]
                    ) + abs(data[code][1]):
                        code_rowpos[code] = chunk_code_rowpos.get(
                            code, code_rowpos.get(code, 0)
                        )

        if not data:
            return ValidationResult(
                status="WARN: Balance sheet - không tìm thấy mã tài khoản hợp lệ",
                marks=[],
                cross_ref_marks=[],
            )

        # Get column positions for marking
        try:
            cur_col_pos = header.index(cur_col)
            prior_col_pos = header.index(prior_col)
        except ValueError:
            cur_col_pos = len(header) - 2
            prior_col_pos = len(header) - 1

        # Use vectorized validation for rules (same as standard)
        rules = get_balance_rules()
        issues, marks = self._validate_balance_sheet_vectorized(
            data, code_rowpos, cur_col, prior_col, header, header_idx, rules
        )

        # Generate status
        if not issues:
            status = "PASS: Balance sheet - kiểm tra công thức: KHỚP (0 sai lệch) [Chunked processing]"
        else:
            preview = "; ".join(issues[:10])
            more = f" ... (+{len(issues) - 10} dòng)" if len(issues) > 10 else ""
            status = f"FAIL: Balance sheet - kiểm tra công thức: {
                len(issues)} sai lệch. {preview}{more} [Chunked processing]"

        return ValidationResult(status=status, marks=marks, cross_ref_marks=[])
