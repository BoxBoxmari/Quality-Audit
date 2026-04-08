"""
Table normalization utility for financial statement tables.

Handles header canonicalization, Code column detection with synonyms,
and pattern-based column detection.
"""

import logging
import re
from typing import Any, Dict, List, Optional, Tuple

import pandas as pd

from ..config.feature_flags import get_feature_flags
from .column_detector import ColumnDetector
from .column_roles import ROLE_CODE, infer_column_roles

logger = logging.getLogger(__name__)


class TableNormalizer:
    """Normalize table headers and detect canonical columns."""

    # Synonyms for Code column
    # SCRUM-6: Expanded with common Vietnamese patterns and CJCGV/CP variations
    CODE_SYNONYMS = [
        # English
        "code",
        "no.",
        "no",
        "number",
        "num",
        "item",
        "ref",
        "reference",
        # "note",  # Removed per V-7
        "account",
        "acct",
        "acc",
        "line",
        "row",
        "id",
        # English multi-word (common in financial statements)
        "particulars",
        "description",
        "line item",
        "content",
        # Vietnamese
        "mã",
        "mã số",
        "số",
        "stt",
        "tt",
        "thứ tự",
        "chỉ tiêu",
        "mục",
        "khoản mục",
        "tài khoản",
        "tk",
        "ms",  # Vietnamese abbreviation for "Mã số"
        "desc",  # Abbreviation for Description (common in tables)
        "unknown",  # Ambiguous header often used for code column
        # Vietnamese multi-word (CJCGV/CP Vietnam DOCX headers)
        "mã số tài khoản",
        "thuyết minh",
        "nội dung",
        # "tm", # Removed per V-7
        # "notes", # Removed per V-7
    ]

    # When multiple columns are code-like, prefer these (explicit code over notes/description).
    PRIORITY_CODE_SYNONYMS = [
        "mã số",
        "code",
        "no.",
        "no",
        "stt",
        "ms",
        "mã",
        "số",
        "tt",
        "number",
        "num",
        "item",
        "ref",
        "line",
        "row",
        "id",
        "account",
        "acct",
        "tk",
        "chỉ tiêu",
        "mục",
        "khoản mục",
        "tài khoản",
        "mã số tài khoản",
        "desc",
        "unknown",
    ]

    # Prefixes: if normalized header starts with one of these, treat as code column.
    # Catches "Mã số tài khoản", "Thuyết minh chi tiết", "Particulars of ...", etc.
    CODE_PREFIXES_NORMALIZED = [
        "mã số ",
        "thuyết minh ",
        "particulars ",
        "description ",
        "nội dung ",
        "line item ",
        "chỉ tiêu ",
    ]

    # Patterns for code-like columns (numeric or alphanumeric codes)
    CODE_PATTERNS = [
        r"^\d+$",  # Pure numeric
        r"^[A-Z]\d+$",  # Alphanumeric like "A1", "B123"
        r"^\d+[A-Z]?$",  # Numeric with optional letter suffix
        r"^[A-Z][\.\-]\d+$",  # Separated alphanumeric like "V.09", "A-1"
        r"^[\d\.]+$",  # Numeric with dots like "1.2.3"
        r"^[IVXLCDM]+(\.[\d]+)?$",  # Roman numerals like "IX", "V.1"
    ]

    _CODE_VALUE_PATTERN = re.compile(
        r"^(\d{1,4}[a-zA-Z]?$|[a-zA-Z]{1,3}\d{1,4}[a-zA-Z]?$|[ivxlcdm]+)$",
        re.IGNORECASE,
    )

    @staticmethod
    def normalize_table(
        df: pd.DataFrame, heading: str | None = None
    ) -> tuple[pd.DataFrame, dict[str, Any]]:
        """
        Normalize table headers and detect canonical columns.

        Args:
            df: Input DataFrame (may have headers in body or clean columns)
            heading: Optional table heading for context

        Returns:
            Tuple of (normalized_df, metadata) where metadata contains:
            - detected_code_column: str or None
            - detected_cur_col: str or None
            - detected_prior_col: str or None
            - header_row_idx: int or -1 if columns already clean
            - normalized_columns: List[str] - final column names
        """
        if df.empty:
            return df, {
                "detected_code_column": None,
                "detected_cur_col": None,
                "detected_prior_col": None,
                "header_row_idx": -1,
                "normalized_columns": [],
            }

        # NOTE: Phase 1 will extend metadata; Phase 0 tests lock prior shape and will be updated.
        metadata: dict[str, Any] = {
            "detected_code_column": None,
            "detected_cur_col": None,
            "detected_prior_col": None,
            "header_row_idx": -1,
            "normalized_columns": list(df.columns),
        }

        # Step 1: Check if DataFrame already has clean columns (no header in body)
        # This happens when WordReader already extracted headers
        # SCRUM-6: Use CODE_SYNONYMS for consistent detection
        columns_lower = [str(c).strip().lower() for c in df.columns]
        has_code_in_columns = any(
            any(syn in col for syn in TableNormalizer.CODE_SYNONYMS)
            for col in columns_lower
        )

        if has_code_in_columns:
            # DataFrame already has clean columns - use them directly
            normalized_df = df.copy()
            metadata["header_row_idx"] = -1
            metadata["normalized_columns"] = list(df.columns)
        else:
            # Step 2: Find header row in body
            # Try multi-row header first
            header_result = TableNormalizer._find_multi_row_header(df)
            if header_result:
                header_idx, merged_header = header_result
                normalized_df = df.iloc[header_idx + 1 :].copy()
                normalized_df.columns = merged_header
                metadata["header_row_idx"] = header_idx
                metadata["normalized_columns"] = merged_header
            else:
                # Try single-row header
                single_header_idx: Optional[int] = TableNormalizer._find_header_row(df)
                if single_header_idx is not None:
                    header_idx = single_header_idx
                    header = [str(c).strip() for c in df.iloc[header_idx].tolist()]
                    normalized_df = df.iloc[header_idx + 1 :].copy()
                    normalized_df.columns = header
                    metadata["header_row_idx"] = header_idx
                    metadata["normalized_columns"] = header
                else:
                    # No header found - use existing columns
                    normalized_df = df.copy()
                    metadata["header_row_idx"] = -1
                    metadata["normalized_columns"] = list(df.columns)

        # Step 3: Detect Code column with synonyms and patterns
        code_col = TableNormalizer._detect_code_column_with_synonyms(normalized_df)
        effective_code_col, code_column_evidence = (
            TableNormalizer._detect_effective_code_column(normalized_df, code_col)
        )
        metadata["detected_code_column"] = code_col
        metadata["effective_code_column"] = effective_code_col
        metadata["code_column_evidence"] = code_column_evidence

        # Step 4: Detect current and prior year columns
        cur_col, prior_col = ColumnDetector.detect_financial_columns_advanced(
            normalized_df
        )

        # B1/B4: Deduplicate/Coalesce duplicate period columns + suspicious table flags
        flags = get_feature_flags()
        metadata["dedup_period_columns_applied"] = False
        metadata["duplicated_period_groups"] = []
        metadata["dedup_conflicts"] = []
        metadata["suspicious_wide_table"] = False
        metadata["suspicious_wide_table_reasons"] = []
        metadata["misalignment_suspected"] = False
        metadata["misalignment_reasons"] = []

        if flags.get("dedup_period_columns", True):
            normalized_df, dedup_meta = TableNormalizer._dedup_period_columns(
                normalized_df
            )
            metadata["dedup_period_columns_applied"] = True
            metadata["duplicated_period_groups"] = dedup_meta.get(
                "duplicated_period_groups", []
            )
            metadata["dedup_conflicts"] = dedup_meta.get("dedup_conflicts", [])
            if dedup_meta.get("columns_dropped"):
                # Re-detect columns after structural change
                cur_col, prior_col = ColumnDetector.detect_financial_columns_advanced(
                    normalized_df
                )

            # B4: suspicious wide table
            if dedup_meta.get("suspicious_wide_table"):
                metadata["suspicious_wide_table"] = True
                metadata["suspicious_wide_table_reasons"] = dedup_meta.get(
                    "suspicious_wide_table_reasons", []
                )
            if dedup_meta.get("misalignment_suspected"):
                metadata["misalignment_suspected"] = True
                metadata["misalignment_reasons"] = dedup_meta.get(
                    "misalignment_reasons", []
                )

        metadata["detected_cur_col"] = cur_col
        metadata["detected_prior_col"] = prior_col

        return normalized_df, metadata

    @staticmethod
    def _code_match_ratio(series: pd.Series) -> float:
        non_empty = series.astype(str).str.strip()
        non_empty = non_empty[(non_empty != "") & (non_empty.str.lower() != "nan")]
        if non_empty.empty:
            return 0.0
        match_count = non_empty.map(
            lambda v: bool(TableNormalizer._CODE_VALUE_PATTERN.match(str(v).strip()))
        ).sum()
        return float(match_count) / float(len(non_empty))

    @staticmethod
    def _description_column_index(df: pd.DataFrame) -> int:
        text_headers = (
            "description",
            "particulars",
            "item",
            "account",
            "nội dung",
            "chỉ tiêu",
        )
        for idx, col in enumerate(df.columns):
            c = str(col).strip().lower()
            if any(k in c for k in text_headers):
                return idx
        return 1 if len(df.columns) > 1 else 0

    @staticmethod
    def _detect_effective_code_column(
        df: pd.DataFrame, declared_code_column: Optional[str]
    ) -> Tuple[Optional[str], Dict[str, Any]]:
        """
        Choose effective code column deterministically:
        1) highest code-match ratio
        2) closest to description column
        3) stable column order fallback
        """
        if df is None or df.empty:
            return declared_code_column, {
                "candidates": [],
                "chosen": declared_code_column,
            }

        candidates = []
        for idx, col in enumerate(df.columns):
            ratio = TableNormalizer._code_match_ratio(df[col])
            header_norm = TableNormalizer.normalize_header(str(col))
            header_like = bool(
                TableNormalizer._CODE_HEADER_PATTERN.match(header_norm)
                or header_norm
                in {
                    TableNormalizer.normalize_header(s)
                    for s in TableNormalizer.PRIORITY_CODE_SYNONYMS
                }
            )
            if header_like or ratio >= 0.45:
                candidates.append((col, idx, ratio, header_like))

        if not candidates:
            return declared_code_column, {
                "candidates": [],
                "chosen": declared_code_column,
                "reason": "no_code_like_candidate",
            }

        desc_idx = TableNormalizer._description_column_index(df)
        # Deterministic sort by ratio(desc), header_like(desc), proximity(asc), index(asc)
        candidates_sorted = sorted(
            candidates,
            key=lambda x: (-x[2], -int(x[3]), abs(x[1] - desc_idx), x[1]),
        )
        best_col = str(candidates_sorted[0][0]).strip()

        # Keep declared code column when it is effectively equivalent to best candidate.
        if declared_code_column:
            declared_ratio = TableNormalizer._code_match_ratio(df[declared_code_column])
            best_ratio = candidates_sorted[0][2]
            if declared_ratio >= (best_ratio - 0.03):
                best_col = declared_code_column

        return best_col, {
            "description_col_idx": desc_idx,
            "candidates": [
                {
                    "column": str(col),
                    "idx": idx,
                    "code_match_ratio": round(ratio, 4),
                    "header_like": bool(header_like),
                }
                for col, idx, ratio, header_like in candidates_sorted
            ],
            "chosen": best_col,
        }

    @staticmethod
    def _extract_period_key(col_name: str) -> Optional[str]:
        """
        Extract a normalized period key from a header string.

        - Prefer full dates (dd/mm/yyyy or mm/dd/yyyy) when present.
        - Otherwise use the first 4-digit year token.
        """
        s = str(col_name)
        # Date-like patterns: 31/12/2018, 12/31/2018, 31-12-2018
        m = re.search(r"(\d{1,2})[\/\-](\d{1,2})[\/\-](\d{2,4})", s)
        if m:
            d1, d2, y = m.group(1), m.group(2), m.group(3)
            if len(y) == 2:
                # 2-digit year fallback; treat as 20xx
                y = f"20{y}"
            # Keep original order to avoid locale assumptions, but normalize separators.
            return f"{int(d1):02d}/{int(d2):02d}/{int(y):04d}"
        y = re.search(r"\d{4}", s)
        if y:
            return y.group()
        return None

    @staticmethod
    def _numeric_density(series: pd.Series) -> int:
        """Count non-NaN numeric cells after coercion."""
        coerced = series.apply(lambda x: pd.to_numeric(str(x), errors="coerce"))
        return int(coerced.notna().sum())

    @staticmethod
    def _dedup_period_columns(df: pd.DataFrame) -> Tuple[pd.DataFrame, Dict[str, Any]]:
        """
        Deduplicate/coalesce duplicate period columns (B1).

        Algorithm (simplified but spec-aligned):
        - Group columns by extracted period key.
        - For groups with >1 columns, select primary column by numeric density.
        - Fill missing primary cells from duplicates.
        - Log conflicts when both cells exist but differ after numeric coercion.
        - Drop non-primary columns.
        """
        out = df.copy()

        period_map: Dict[str, List[str]] = {}
        for col in out.columns:
            key = TableNormalizer._extract_period_key(str(col))
            if not key:
                continue
            period_map.setdefault(key, []).append(col)

        duplicated_groups: List[Dict[str, Any]] = []
        conflicts: List[Dict[str, Any]] = []
        columns_dropped: List[str] = []

        for key, cols in period_map.items():
            if len(cols) <= 1:
                continue

            # P2.1: Choose primary by numeric evidence (density); keep column with higher numeric evidence
            densities = [(c, TableNormalizer._numeric_density(out[c])) for c in cols]
            max_density = max(d for _, d in densities)
            primary_col = next(c for c, d in densities if d == max_density)
            logger.debug(
                "P2.1 dedup period_key=%r kept_column=%r densities=%s",
                key,
                str(primary_col),
                {str(c): d for c, d in densities},
            )

            duplicated_groups.append(
                {
                    "period_key": key,
                    "columns": [str(c) for c in cols],
                    "primary": str(primary_col),
                    "numeric_density": {str(c): int(d) for c, d in densities},
                }
            )

            # fill and detect conflicts
            for dup_col in cols:
                if dup_col == primary_col:
                    continue

                primary_vals = out[primary_col]
                dup_vals = out[dup_col]

                # conflict where both numeric and different
                p_num = primary_vals.apply(
                    lambda x: pd.to_numeric(str(x), errors="coerce")
                )
                d_num = dup_vals.apply(lambda x: pd.to_numeric(str(x), errors="coerce"))
                both = p_num.notna() & d_num.notna()
                diff = both & (p_num != d_num)
                has_conflict = diff.any()

                if has_conflict:
                    idxs = diff[diff].index.tolist()[:5]
                    conflicts.append(
                        {
                            "period_key": key,
                            "primary": str(primary_col),
                            "duplicate": str(dup_col),
                            "sample_row_indices": [int(i) for i in idxs],
                        }
                    )
                    logger.warning(
                        "Dedup conflict period=%s primary=%s dup=%s sample_rows=%s",
                        key,
                        primary_col,
                        dup_col,
                        idxs,
                    )
                    # When conflict, rename duplicate column instead of drop (Issue A2)
                    new_name = f"{dup_col} (2)"
                    out = out.rename(columns={dup_col: new_name})
                    logger.info(
                        "Renamed conflicting duplicate column %s -> %s",
                        dup_col,
                        new_name,
                    )
                    continue

                # fill only when primary is null and dup is not null
                fill_mask = primary_vals.isna() & dup_vals.notna()
                if fill_mask.any():
                    out.loc[fill_mask, primary_col] = dup_vals.loc[fill_mask]

                columns_dropped.append(str(dup_col))

        if columns_dropped:
            # Drop in one shot; ignore missing defensively
            out = out.drop(columns=columns_dropped, errors="ignore")

        # B4 flags: suspicious wide table
        suspicious = False
        reasons: List[str] = []
        if df.shape[1] >= 20:
            suspicious = True
            reasons.append("column_count>=20")
        if duplicated_groups:
            suspicious = True
            reasons.append("duplicated_period_groups>0")
        if conflicts:
            suspicious = True
            reasons.append("dedup_conflicts>0")

        # B4 flags: misalignment suspicion (metadata only)
        misalignment_suspected = False
        misalignment_reasons: List[str] = []
        if period_map and df.shape[1] >= 3:
            first_col_name = str(df.columns[0]).strip().lower()
            first_col_density = TableNormalizer._numeric_density(df.iloc[:, 0])
            # If the first column header does not look like code/desc but numeric density is high,
            # the table may have shifted labels into numeric columns.
            if (
                ("code" not in first_col_name)
                and ("mã" not in first_col_name)
                and ("desc" not in first_col_name)
                and ("description" not in first_col_name)
                and first_col_density >= max(1, int(0.7 * len(df)))
            ):
                misalignment_suspected = True
                misalignment_reasons.append("first_column_high_numeric_density")

        return out, {
            "duplicated_period_groups": duplicated_groups,
            "dedup_conflicts": conflicts,
            "columns_dropped": columns_dropped,
            "suspicious_wide_table": suspicious,
            "suspicious_wide_table_reasons": reasons,
            "misalignment_suspected": misalignment_suspected,
            "misalignment_reasons": misalignment_reasons,
        }

    @staticmethod
    def _find_multi_row_header(
        df: pd.DataFrame, code_col_name: str = "code"
    ) -> tuple[int, list[str]] | None:
        """
        Find multi-row header and merge header information.

        Args:
            df: DataFrame to search
            code_col_name: Name of the code column

        Returns:
            Optional[Tuple[int, List[str]]]: (header_start_idx, merged_header_columns) or None
        """
        if df.empty:
            return None

        # P2.1: Scan top 5-8 rows for header; preserve date tokens in merged header
        max_header_rows = min(8, len(df))

        # Find first row with code column
        header_start = None
        for i in range(max_header_rows):
            if i >= len(df):
                break

            try:
                row_strs = df.iloc[i].astype(str).str.lower()
                if row_strs.str.contains(code_col_name.lower()).any():
                    header_start = i
                    break
            except (IndexError, KeyError):
                continue

        if header_start is None:
            return None

        # Merge header rows (combine non-empty cells from multiple rows)
        # P2.1: Use up to 8 rows; preserve date tokens (dd/mm/yyyy, mm/dd/yyyy)
        date_header_pattern = re.compile(
            r"(\d{1,2}/\d{1,2}/\d{4}|\d{4}/\d{1,2}/\d{1,2}|\d{1,2}-\d{1,2}-\d{4}|\d{4}-\d{1,2}-\d{1,2})"
        )
        merge_depth = min(8, len(df) - header_start)
        merged_header = []
        max_cols = len(df.columns) if not df.empty else 0

        for col_idx in range(max_cols):
            header_parts = []
            for row_offset in range(merge_depth):
                row_idx = header_start + row_offset
                if row_idx < len(df) and col_idx < len(df.columns):
                    cell_val = str(df.iloc[row_idx, col_idx]).strip()
                    if cell_val and cell_val.lower() not in ["", "nan", "none"]:
                        header_parts.append(cell_val)

            # Combine header parts; preserve date tokens (e.g. "1/1/2018" in CP tbl_014, CJ tbl_021)
            merged_cell = (
                " ".join(header_parts) if header_parts else f"Column{col_idx + 1}"
            )
            if date_header_pattern.search(merged_cell):
                logger.debug(
                    "P2.1 header date preserved col_idx=%s merged=%r",
                    col_idx,
                    merged_cell[:80],
                )
            merged_header.append(merged_cell)

        return (header_start, merged_header)

    @staticmethod
    def _find_header_row(
        df: pd.DataFrame, code_col_name: str = "code"
    ) -> Optional[int]:
        """
        Find the header row containing the code column.

        Args:
            df: DataFrame to search
            code_col_name: Name of the code column

        Returns:
            Optional[int]: Index of header row, or None if not found
        """
        if df.empty:
            return None

        # P2.1: Scan top 5-8 rows for header
        max_header_rows = min(8, len(df))

        for i in range(max_header_rows):
            if i >= len(df):
                break

            try:
                row_strs = df.iloc[i].astype(str).str.lower()
                if row_strs.str.contains(code_col_name.lower()).any():
                    return i
            except (IndexError, KeyError):
                continue

        return None

    @staticmethod
    def normalize_header(col_name: str) -> str:
        """Normalize header for matching: lower case and collapse whitespace."""
        return " ".join(str(col_name).strip().lower().split())

    # Regex for code-like column names: base name + optional .1, .2, ...
    # Matches: code, code.1, code.2, no, no., no.1, stt, mã, ma, ref, ref.1, index, etc.
    _CODE_HEADER_PATTERN = re.compile(
        r"^(code|no\.?|stt|mã|ma|ref\.?|index|num|id)(\.\d+)?$"
    )

    @staticmethod
    def _detect_code_columns_with_synonyms(df: pd.DataFrame) -> List[str]:
        """
        Detect ALL code-like columns via role-based inference.

        Uses infer_column_roles (CODE | LABEL | NUMERIC | OTHER) so that
        ROLE_CODE columns are excluded from numeric normalization and sum/total checks.
        Returns columns in original DataFrame order.
        """
        if len(df.columns) == 0:
            return []
        roles, _, _ = infer_column_roles(df, header_row=0, context=None)
        code_like = [
            str(c).strip() for c in df.columns if roles.get(str(c).strip()) == ROLE_CODE
        ]
        explicit_code_headers = [
            c
            for c in code_like
            if TableNormalizer._CODE_HEADER_PATTERN.match(
                TableNormalizer.normalize_header(c)
            )
        ]
        # Compatibility contract:
        # - include Description as code-like only in multi-code header variants
        #   with 1..2 explicit code headers (e.g. Code + Code.1),
        # - do not include it when no explicit code header exists,
        # - do not include it when there are already 3+ explicit code headers.
        if 1 <= len(explicit_code_headers) <= 2:
            for col in df.columns:
                col_name = str(col).strip()
                col_norm = TableNormalizer.normalize_header(col_name)
                if "description" in col_norm and col_name not in code_like:
                    code_like.append(col_name)
        return code_like

    @staticmethod
    def _detect_code_column_with_synonyms(df: pd.DataFrame) -> str | None:
        """
        Detect first Code column (backward-compatible single-column API).

        When multiple columns are code-like, prefers explicit code synonyms (e.g. Mã số, Code)
        over notes/description synonyms (e.g. Thuyết minh, Particulars).
        """
        code_cols = TableNormalizer._detect_code_columns_with_synonyms(df)
        if not code_cols:
            return None
        priority_norm = {
            TableNormalizer.normalize_header(s)
            for s in TableNormalizer.PRIORITY_CODE_SYNONYMS
        }
        for col in code_cols:
            col_norm = TableNormalizer.normalize_header(col)
            if col_norm in priority_norm or TableNormalizer._CODE_HEADER_PATTERN.match(
                col_norm
            ):
                return col
        return code_cols[0]
