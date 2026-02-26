"""
Python-docx fallback extractor: reconstruct table grid using python-docx API
(table.rows, cell.text, gridSpan/vMerge). Logic extracted from WordReader._reconstruct_table_grid
with ExtractionResult and quality scoring.
"""

import logging
import re
from typing import Any, List, Optional, Tuple

from .ooxml_table_grid_extractor import Cell, ExtractionResult

logger = logging.getLogger(__name__)

W_NS = "{http://schemas.openxmlformats.org/wordprocessingml/2006/main}"
QUALITY_THRESHOLD = 0.6


class PythonDocxExtractor:
    """
    Fallback extractor using python-docx Table API (same reconstruction as
    WordReader._reconstruct_table_grid). Produces ExtractionResult with
    quality_score; used when OOXML engine fails.
    """

    def extract(self, table: Any) -> ExtractionResult:
        """
        Extract grid from a python-docx Table, then score quality.

        Args:
            table: docx.table.Table instance.

        Returns:
            ExtractionResult with grid, quality_score, quality_flags.
        """
        try:
            grid, cells, vmerge_violations = self._reconstruct_grid(table)
        except Exception as e:
            logger.warning("Python-docx fallback extraction failed: %s", e)
            return ExtractionResult(
                grid=[],
                quality_score=0.0,
                quality_flags=["extraction_failed", "PYTHON_DOCX_FALLBACK"],
                invariant_violations=[f"exception: {e!s}"],
                failure_reason_code="EXTRACTION_FAILED",
            )

        if not grid:
            return ExtractionResult(
                grid=[],
                quality_score=0.0,
                quality_flags=["empty_grid", "PYTHON_DOCX_FALLBACK"],
                failure_reason_code="EMPTY_GRID",
            )

        rows, cols = len(grid), max(len(r) for r in grid) if grid else 0
        expected_cols = self._get_tbl_grid_col_count(table)
        invariant_violations = self._check_invariants(
            grid, rows, cols, expected_cols=expected_cols
        )
        invariant_violations = list(invariant_violations) + list(vmerge_violations)
        quality_score, quality_flags = self._score_quality(
            grid, rows, cols, invariant_violations
        )
        quality_flags = quality_flags or []
        quality_flags.append("PYTHON_DOCX_FALLBACK")
        failure_reason_code = self._derive_failure_reason_code(
            invariant_violations, quality_flags
        )

        return ExtractionResult(
            grid=grid,
            cells=cells,
            quality_score=quality_score,
            quality_flags=quality_flags,
            rows=rows,
            cols=cols,
            invariant_violations=invariant_violations,
            failure_reason_code=failure_reason_code,
        )

    def _reconstruct_grid(
        self, table: Any
    ) -> Tuple[List[List[str]], List[Cell], List[str]]:
        """Reconstruct 2D grid, cells, and vmerge_violations (vMerge continue without restart)."""
        vmerge_violations: List[str] = []
        max_cols = 0
        for row in table.rows:
            col_count = 0
            for cell in row.cells:
                try:
                    cell_elem = cell._element
                    gs = cell_elem.xpath(".//*[local-name()='gridSpan']")
                    span = 1
                    if gs:
                        val = gs[0].get(f"{W_NS}val") or gs[0].get("val")
                        if val is not None:
                            span = max(1, int(val))
                    col_count += span
                except (ValueError, TypeError, AttributeError):
                    col_count += 1
            max_cols = max(max_cols, col_count)

        if max_cols == 0:
            return [], [], []

        grid = [["" for _ in range(max_cols)] for _ in range(len(table.rows))]
        active_vmerge: List[Optional[str]] = [None] * max_cols
        cells: List[Cell] = []

        for r_idx, row in enumerate(table.rows):
            col_ptr = 0
            for cell in row.cells:
                raw_text = cell.text or ""
                normalized = raw_text.replace("\u00a0", " ").replace("\n", " ").strip()
                normalized = re.sub(r"\s+", " ", normalized)

                cell_elem = cell._element
                span = 1
                gs = cell_elem.xpath(".//*[local-name()='gridSpan']")
                if gs:
                    val = gs[0].get(f"{W_NS}val") or gs[0].get("val")
                    if val is not None:
                        span = max(1, int(val))

                vm = cell_elem.xpath(".//*[local-name()='vMerge']")
                v_val: Optional[str] = None
                if vm:
                    v_val = vm[0].get(f"{W_NS}val") or vm[0].get("val") or "continue"
                    v_val = str(v_val).strip().lower()
                    if v_val not in ("restart", "continue"):
                        v_val = "continue"

                while col_ptr < max_cols and grid[r_idx][col_ptr] != "":
                    col_ptr += 1
                if col_ptr >= max_cols:
                    break

                final_text: Optional[str] = normalized
                if v_val == "restart":
                    for i in range(span):
                        if col_ptr + i < max_cols:
                            active_vmerge[col_ptr + i] = normalized
                elif v_val == "continue":
                    if active_vmerge[col_ptr] is not None:
                        final_text = active_vmerge[col_ptr]
                    else:
                        vmerge_violations.append(
                            f"vmerge_misalign_row_{r_idx}_col_{col_ptr}"
                        )
                else:
                    for i in range(span):
                        if col_ptr + i < max_cols:
                            active_vmerge[col_ptr + i] = None

                for i in range(span):
                    if col_ptr + i < max_cols and final_text is not None:
                        grid[r_idx][col_ptr + i] = final_text
                        cells.append(
                            Cell(
                                row=r_idx,
                                col=col_ptr + i,
                                value=final_text,
                                col_span=1,
                                row_span=1,
                            )
                        )
                col_ptr += span

        return grid, cells, vmerge_violations

    def _get_tbl_grid_col_count(self, table: Any) -> Optional[int]:
        """Return number of columns from tblGrid (w:gridCol children), or None if absent."""
        try:
            tbl = getattr(table, "_element", None)
            if tbl is None:
                return None
            tbl_grid = tbl.xpath(".//*[local-name()='tblGrid']")
            if not tbl_grid:
                return None
            grid_cols = tbl_grid[0].xpath(".//*[local-name()='gridCol']")
            return len(grid_cols) if grid_cols else None
        except (AttributeError, IndexError):
            return None

    def _derive_failure_reason_code(
        self,
        invariant_violations: List[str],
        quality_flags: List[str],
    ) -> Optional[str]:
        """Derive failure_reason_code from invariant_violations and quality_flags."""
        if "GRID_CORRUPTION" in quality_flags or any(
            v.startswith("row_") and "col_count" in v for v in invariant_violations
        ):
            return "GRID_CORRUPTION"
        if "tblGrid_col_mismatch" in invariant_violations:
            return "GRID_CORRUPTION"
        if (
            any("vmerge_misalign" in v for v in invariant_violations)
            or "VMERGE_MISALIGN" in quality_flags
        ):
            return "VMERGE_MISALIGN"
        if (
            "duplicate_periods" in invariant_violations
            or "DUPLICATE_PERIODS" in quality_flags
        ):
            return "DUPLICATE_PERIODS"
        return None

    def _check_invariants(
        self,
        grid: List[List[str]],
        rows: int,
        cols: int,
        expected_cols: Optional[int] = None,
    ) -> List[str]:
        """Check grid invariants; return list of violation messages."""
        violations: List[str] = []
        if rows == 0 or cols == 0:
            violations.append("empty_grid")
            return violations
        for r, row in enumerate(grid):
            if len(row) != cols:
                violations.append(f"row_{r}_col_count_{len(row)}_expected_{cols}")
        if expected_cols is not None and cols != expected_cols:
            violations.append("tblGrid_col_mismatch")
        if grid and len(grid[0]) == cols:
            header = [str(c).strip() for c in grid[0]]
            if len(header) != len(set(header)):
                violations.append("duplicate_periods")
        return violations

    def _score_quality(
        self,
        grid: List[List[str]],
        rows: int,
        cols: int,
        invariant_violations: List[str],
    ) -> Tuple[float, List[str]]:
        """Compute quality_score in [0.0, 1.0] and quality_flags."""
        flags: List[str] = []
        score = 1.0

        if invariant_violations:
            if "empty_grid" in invariant_violations:
                return 0.0, ["empty_grid"]
            if "duplicate_periods" in invariant_violations:
                flags.append("DUPLICATE_PERIODS")
                score -= 0.4
            for v in invariant_violations:
                if v.startswith("row_") and "col_count" in v:
                    flags.append("GRID_CORRUPTION")
                    score -= 0.5
                    break
            if "tblGrid_col_mismatch" in invariant_violations:
                flags.append("GRID_CORRUPTION")
                score -= 0.5
            if any("vmerge_misalign" in v for v in invariant_violations):
                flags.append("VMERGE_MISALIGN")
                score -= 0.5

        total = rows * cols
        if total == 0:
            return 0.0, flags or ["empty_grid"]
        filled = sum(1 for r in grid for c in r if str(c).strip())
        fill_ratio = filled / total
        if fill_ratio < 0.1:
            score -= 0.3
            flags.append("LOW_FILL")
        elif fill_ratio < 0.5:
            score -= 0.1

        score = max(0.0, min(1.0, score))
        if {"GRID_CORRUPTION", "VMERGE_MISALIGN", "DUPLICATE_PERIODS"} & set(flags):
            score = min(score, 0.55)
        return round(score, 2), flags
