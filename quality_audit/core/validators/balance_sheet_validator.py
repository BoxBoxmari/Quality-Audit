"""
Balance Sheet validator implementation.
"""

import logging
from typing import Any, Dict, List, Optional, Tuple

import pandas as pd

from ...config.validation_rules import get_balance_rules
from ...utils.chunk_processor import ChunkProcessor
from ...utils.column_detector import ColumnDetector
from ...utils.numeric_utils import parse_numeric
from ..parity.legacy_baseline import (
    KEY_AP_LONG,
    KEY_AR_LONG_ASCII,
    accumulate_net_dta_dtl,
    update_legacy_combined_keys,
)
from .base_validator import BaseValidator, ValidationResult

logger = logging.getLogger(__name__)


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
            is_ok_cy = abs(round(diff_cy)) == 0
            is_ok_py = abs(round(diff_py)) == 0

            # Find missing children using vectorized operations
            all_child_codes = set(child_norms)
            existing_codes = set(data_df["code"].unique())
            missing = list(all_child_codes - existing_codes)

            # Create marks
            if parent_norm in code_rowpos:
                # SCRUM-11: If header_idx = -1, header already promoted, no offset needed
                df_row = (
                    (header_idx + 1 + code_rowpos[parent_norm])
                    if header_idx >= 0
                    else code_rowpos[parent_norm]
                )
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

    def validate(
        self,
        df: pd.DataFrame,
        heading: Optional[str] = None,
        table_context: Optional[Dict] = None,
    ) -> ValidationResult:
        """
        Validate balance sheet table with automatic chunked processing for large tables.

        Args:
            df: DataFrame containing balance sheet data
            heading: Table heading (unused for balance sheet)
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
            if df is None or df.empty:
                return ValidationResult(
                    status="WARN: Balance sheet - bảng rỗng (empty table)",
                    marks=[],
                    cross_ref_marks=[],
                )

            # P2-T1: Use centralized TableNormalizer
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
                # It means detection failed or no header found.
                # Check if we have a default "code" column?
                # If not, warn.
                # Try fallback to legacy 'check "Code" in existing columns' just in case
                code_col = next(
                    (c for c in df_norm.columns if str(c).strip().lower() == "code"),
                    None,
                )
            # Guardrail: if an explicit "Code" header exists, prefer it over any
            # inferred non-code column selected by heuristics (e.g., "ASSETS", "Column_0").
            explicit_code_col = next(
                (c for c in df_norm.columns if str(c).strip().lower() == "code"), None
            )
            if explicit_code_col is not None and (
                code_col is None or str(code_col).strip().lower() != "code"
            ):
                code_col = explicit_code_col
                metadata["code_column"] = explicit_code_col
                metadata["effective_code_column"] = explicit_code_col

            if not code_col:
                # Last ditch: try to detect it again if Normalizer missed it (unlikely)
                from ...utils.table_normalizer import TableNormalizer

                code_col = TableNormalizer._detect_code_column_with_synonyms(df_norm)
            if not code_col and "__canonical_code__" in df_norm.columns:
                code_col = "__canonical_code__"

            if not code_col:
                canon = metadata.get("canon_report") or {}
                flags = canon.get("flags") or {}
                rule_id = (
                    "UNDETERMINED_HEADER_AFTER_CANONICALIZE"
                    if metadata.get("canonicalization_applied") and flags
                    else "MISSING_CODE_COLUMN"
                )
                return ValidationResult(
                    status="WARN: Balance sheet - không tìm thấy cột 'Code' để kiểm tra",
                    marks=[],
                    cross_ref_marks=[],
                    rule_id=rule_id,
                    status_enum="INFO_SKIPPED",
                    context={"failure_reason_code": rule_id, **metadata},
                )

            # Check if table is large enough to use chunked processing
            if len(df_norm) > self.LARGE_TABLE_THRESHOLD:
                result = self._validate_large_table_chunked(
                    df_norm, list(df_norm.columns), -1, heading, metadata
                )
            else:
                result = self._validate_standard(
                    df_norm, list(df_norm.columns), -1, heading, metadata
                )
            result = self._enforce_pass_gating(
                result,
                result.assertions_count,
                metadata.get("numeric_evidence_score", 0.0),
            )
            return self._apply_warn_capping(result, table_context)
        except Exception as e:
            logger.exception("Balance sheet validator logic failed")
            return ValidationResult(
                status="FAIL_TOOL_LOGIC: Validator exception",
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

    def _validate_standard(
        self,
        tmp: pd.DataFrame,
        header: List[str],
        header_idx: int,
        heading: Optional[str] = None,
        metadata: Optional[Dict[str, Any]] = None,
    ) -> ValidationResult:
        """
        Validate standard-sized balance sheet table (non-chunked).

        Args:
            tmp: DataFrame with proper headers (data rows only, no header row)
            header: List of header column names
            header_idx: Index of header row in original DataFrame (unused in normalized flow usually)
            heading: Table heading (unused)

        Returns:
            ValidationResult: Validation results
        """

        # Identify columns
        # Code column should be detected by now, but we get it from columns for safety
        code_col = (metadata or {}).get("effective_code_column") or (
            metadata or {}
        ).get("code_column")
        # If TableNormalizer identified a different name for code, use it.
        # But _normalize_table_with_metadata doesn't rename the column to "code" automatically?
        # TableNormalizer.normalize_table RETURNS data with found headers as columns.
        # If the header was "Mã số", the column name is "Mã số".
        # So we must use metadata detection or synonyms again.

        # P2-T1: Re-detect to be sure or use what is in tmp.columns
        # Note: TableNormalizer doesn't standardise the *name* of the column to 'Code',
        # it just standardizes the *dataframe structure* (finding the header row).
        # But BaseValidator._normalize_table_with_metadata returns metadata["code_column"].

        # In this method scopes, we don't have 'metadata' passed in.
        # So we re-detect.
        from ...utils.table_normalizer import TableNormalizer

        if code_col is None:
            code_col = TableNormalizer._detect_code_column_with_synonyms(tmp)

        if code_col is None:
            return ValidationResult(
                status="WARN: Balance sheet - không xác định được cột 'Code'",
                marks=[],
                cross_ref_marks=[],
            )

        # SCRUM-11: Improved Note column detection (case-insensitive, partial match)
        # ... existing logic ...

        note_col = ColumnDetector.detect_note_column(tmp)
        if note_col is None:
            # Fallback
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
                context={
                    "failure_reason_code": "NO_NUMERIC_EVIDENCE",
                    "routing_gate_missed": True,
                },
            )

        # Vectorized data extraction and cache operations
        # Normalize codes using vectorized operations
        code_series = (
            tmp["__canonical_code__"]
            if "__canonical_code__" in tmp.columns
            else tmp[code_col]
        )
        tmp["_normalized_code"] = code_series.apply(self._normalize_code)

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
        cache = self._active_cross_check_cache()
        data: Dict[str, Any] = {}
        code_rowpos: Dict[str, int] = {}

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
            # SCRUM-11: Improved Note column caching - also cache by code if Note column exists but account name is empty
            if note_col and row.get(note_col, "") != "":
                acc_name = row.get(tmp.columns[0], "").strip().lower()
                if acc_name:
                    cache.set(acc_name, (cur_val, prior_val))
                # Fallback: If account name is empty but Note column has value, cache by code
                elif code and code in ["141", "149", "251", "252", "253", "254"]:
                    # Cache by code as fallback when Note column exists but account name is missing
                    cache.set(code, (cur_val, prior_val))
            elif code in {"131", "211", "311", "331"}:
                # Keep AR/AP short/long-term codes available for combined legacy mappings.
                cache.set(code, (cur_val, prior_val))
                if code == "131":
                    cache.set(
                        "accounts receivable from customers", (cur_val, prior_val)
                    )
                elif code == "211":
                    cache.set(KEY_AR_LONG_ASCII, (cur_val, prior_val))
                elif code == "331":
                    cache.set(
                        "short-term accounts payable to suppliers", (cur_val, prior_val)
                    )
                elif code == "311":
                    cache.set(KEY_AP_LONG, (cur_val, prior_val))
            elif code in ["141", "149", "251", "252", "253", "254"]:
                if code in ["251", "252", "253"]:
                    try:
                        old_cur, old_pr = cache.get(
                            "investments in other entities"
                        ) or (0.0, 0.0)
                        cache.set(
                            "investments in other entities",
                            (cur_val + old_cur, prior_val + old_pr),
                        )
                    except Exception:
                        pass
                cache.set(code, (cur_val, prior_val))
            accumulate_net_dta_dtl(cache, code, cur_val, prior_val)

            code_rowpos[code] = ridx - tmp.index[0]

        # Get column positions for marking
        try:
            header.index(cur_col)
            header.index(prior_col)
        except ValueError:
            pass  # Columns not found, will use defaults

        # Use vectorized validation for rules
        use_new_rules, form_signature = self._detect_balance_form_signature(
            data=data,
            heading=heading,
            metadata=metadata or {},
        )
        rules = get_balance_rules(use_new_rules=use_new_rules)
        issues, marks = self._validate_balance_sheet_vectorized(
            data, code_rowpos, cur_col, prior_col, header, header_idx, rules
        )
        update_legacy_combined_keys(cache)

        # Generate status
        if not issues:
            status = "PASS: Balance sheet - kiểm tra công thức: KHỚP (0 sai lệch)"
        else:
            preview = "; ".join(issues[:10])
            more = f" ... (+{len(issues) - 10} dòng)" if len(issues) > 10 else ""
            status = f"FAIL: Balance sheet - kiểm tra công thức: {len(issues)} sai lệch. {preview}{more}"

        # Determine root cause if failed
        root_cause = None
        if issues:
            root_cause = "Calculation Mismatch"

        return ValidationResult(
            status=status,
            marks=marks,
            cross_ref_marks=[],
            detected_columns=list(tmp.columns),
            root_cause=root_cause,
            table_id="Balance Sheet",
            assertions_count=len(marks),
            context={
                "balance_rule_set": "new" if use_new_rules else "old",
                "balance_form_signature": form_signature,
            },
        )

    def _validate_large_table_chunked(
        self,
        tmp: pd.DataFrame,
        header: List[str],
        header_idx: int,
        heading: Optional[str] = None,
        metadata: Optional[Dict[str, Any]] = None,
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
        code_col = (metadata or {}).get("effective_code_column") or (
            metadata or {}
        ).get("code_column")
        if code_col is None:
            return ValidationResult(
                status="WARN: Balance sheet - không xác định được cột 'Code'",
                marks=[],
                cross_ref_marks=[],
            )

        # SCRUM-11: Improved Note column detection (case-insensitive, partial match)
        # Use ColumnDetector for robust detection

        note_col = ColumnDetector.detect_note_column(tmp)
        # Fallback to exact match if ColumnDetector fails
        if note_col is None:
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
                context={
                    "failure_reason_code": "NO_NUMERIC_EVIDENCE",
                    "routing_gate_missed": True,
                },
            )

        # Process in chunks to extract data
        cache = self._active_cross_check_cache()
        chunk_size = self.LARGE_TABLE_THRESHOLD
        data: Dict[str, Any] = {}
        code_rowpos: Dict[str, int] = {}
        base_index = tmp.index[0]  # Store base index for row position calculation

        def process_chunk(chunk: pd.DataFrame) -> Dict:
            """Process a single chunk to extract data."""
            chunk_data: Dict[str, Any] = {}
            chunk_code_rowpos = {}

            # Normalize codes
            code_series = (
                chunk["__canonical_code__"]
                if "__canonical_code__" in chunk.columns
                else chunk[code_col]
            )
            chunk["_normalized_code"] = code_series.apply(self._normalize_code)

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
                # SCRUM-11: Improved Note column caching - also cache by code if Note column exists but account name is empty
                if note_col and row.get(note_col, "") != "":
                    acc_name = row.get(tmp.columns[0], "").strip().lower()
                    if acc_name:
                        cache.set(acc_name, (cur_val, prior_val))
                    # Fallback: If account name is empty but Note column has value, cache by code
                    elif code and code in ["141", "149", "251", "252", "253", "254"]:
                        # Cache by code as fallback when Note column exists but account name is missing
                        cache.set(code, (cur_val, prior_val))
                elif code in {"131", "211", "311", "331"}:
                    # Keep AR/AP short/long-term codes available for combined legacy mappings.
                    cache.set(code, (cur_val, prior_val))
                if code == "131":
                    cache.set(
                        "accounts receivable from customers", (cur_val, prior_val)
                    )
                elif code == "211":
                    cache.set(KEY_AR_LONG_ASCII, (cur_val, prior_val))
                elif code == "331":
                    cache.set(
                        "short-term accounts payable to suppliers", (cur_val, prior_val)
                    )
                elif code == "311":
                    cache.set(KEY_AP_LONG, (cur_val, prior_val))
                elif code in ["141", "149", "251", "252", "253", "254"]:
                    if code in ["251", "252", "253"]:
                        try:
                            old_cur, old_pr = cache.get(
                                "investments in other entities"
                            ) or (0.0, 0.0)
                            cache.set(
                                "investments in other entities",
                                (cur_val + old_cur, prior_val + old_pr),
                            )
                        except Exception:
                            pass
                    cache.set(code, (cur_val, prior_val))
                accumulate_net_dta_dtl(cache, code, cur_val, prior_val)

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
            header.index(cur_col)
            header.index(prior_col)
        except ValueError:
            pass  # Columns not found, will use defaults

        # Use vectorized validation for rules (same as standard)
        use_new_rules, form_signature = self._detect_balance_form_signature(
            data=data,
            heading=heading,
            metadata=metadata or {},
        )
        rules = get_balance_rules(use_new_rules=use_new_rules)
        issues, marks = self._validate_balance_sheet_vectorized(
            data, code_rowpos, cur_col, prior_col, header, header_idx, rules
        )
        update_legacy_combined_keys(cache)

        # Generate status
        if not issues:
            status = "PASS: Balance sheet - kiểm tra công thức: KHỚP (0 sai lệch) [Chunked processing]"
        else:
            preview = "; ".join(issues[:10])
            more = f" ... (+{len(issues) - 10} dòng)" if len(issues) > 10 else ""
            status = f"FAIL: Balance sheet - kiểm tra công thức: {len(issues)} sai lệch. {preview}{more} [Chunked processing]"

        # Determine root cause if failed
        root_cause = None
        if issues:
            root_cause = "Calculation Mismatch"

        return ValidationResult(
            status=status,
            marks=marks,
            cross_ref_marks=[],
            detected_columns=list(tmp.columns),
            root_cause=root_cause,
            table_id="Balance Sheet",
            assertions_count=len(marks),
            context={
                "balance_rule_set": "new" if use_new_rules else "old",
                "balance_form_signature": form_signature,
            },
        )

    def _detect_balance_form_signature(
        self,
        data: Dict[str, Tuple[float, float]],
        heading: Optional[str],
        metadata: Dict[str, Any],
    ) -> Tuple[bool, str]:
        """
        Detect whether table follows old/new balance form signatures.
        """
        if metadata.get("balance_form") in {"new", "old"}:
            selected = metadata["balance_form"] == "new"
            return selected, f"metadata:{metadata['balance_form']}"

        codes = set(data.keys())
        heading_lower = str(heading or "").lower()

        new_form_markers = {
            "160",
            "161",
            "162",
            "163",
            "164",
            "165",
            "280",
            "325",
            "344",
        }
        old_form_markers = {"270", "410", "430", "440"}
        new_hits = len(codes.intersection(new_form_markers))
        old_hits = len(codes.intersection(old_form_markers))

        if "form b01-dn" in heading_lower and (
            "tt200" in heading_lower or "2014/tt-btc" in heading_lower
        ):
            return True, "heading:tt200_b01dn"
        if new_hits > old_hits:
            return True, f"codes:new_hits={new_hits},old_hits={old_hits}"
        return False, f"codes:new_hits={new_hits},old_hits={old_hits}"
