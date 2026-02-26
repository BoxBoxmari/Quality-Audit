"""
OOXML table grid extractor: reconstruct table from tblGrid, gridSpan, vMerge.
Produces ExtractionResult with quality_score (0.0-1.0) and invariant checks.
"""

import logging
import re
from dataclasses import dataclass, field
from typing import Any, List, Optional, Set, Tuple

logger = logging.getLogger(__name__)

# Period/year header patterns (extractor_usable_v2)
_PERIOD_YEAR_PATTERN = re.compile(
    r"^(19|20)\d{2}$|^FY\s*(19|20)?\d{2}$|^\d{1,2}/\d{1,2}/\d{2,4}$|^Q[1-4]\s*(19|20)?\d{2}$|^(Jan|Feb|Mar|Apr|May|Jun|Jul|Aug|Sep|Oct|Nov|Dec)[a-z]*\s*\d{2,4}$",
    re.IGNORECASE,
)
_CODE_NOTE_PATTERN = re.compile(
    r"^(Code|Note|Description|Item|Line)\s*\.?\d*$", re.IGNORECASE
)

# OOXML namespace for w: elements
W_NS = "{http://schemas.openxmlformats.org/wordprocessingml/2006/main}"


@dataclass
class Cell:
    """Single cell in the reconstructed grid."""

    row: int
    col: int
    value: str
    row_span: int = 1
    col_span: int = 1


@dataclass
class ExtractionResult:
    """Result of OOXML table extraction with quality metadata."""

    grid: List[List[str]]
    cells: List[Cell] = field(default_factory=list)
    quality_score: float = 0.0
    quality_flags: List[str] = field(default_factory=list)
    rows: int = 0
    cols: int = 0
    invariant_violations: List[str] = field(default_factory=list)
    failure_reason_code: Optional[str] = None
    # R1 telemetry: grid and merge counts
    grid_cols_expected: Optional[int] = None
    grid_cols_built: int = 0
    grid_span_count: int = 0
    vmerge_count: int = 0

    @property
    def is_usable(self) -> bool:
        """R2: Usable if quality_score >= 0.6 and no hard invariant violations.
        Soft violations (tblGrid_col_mismatch, vmerge_misalign, soft_anomaly) do not force unusable.
        When extractor_usable_v2: require 2+ critical signals to mark unusable.
        """
        hard = self._hard_invariant_violations()
        critical_flags = {"GRID_CORRUPTION", "DUPLICATE_PERIODS"}
        try:
            from ...config.feature_flags import get_feature_flags

            v2 = get_feature_flags().get("extractor_usable_v2", False)
        except Exception:
            v2 = False
        if v2:
            critical_count = len(critical_flags & set(self.quality_flags))
            has_critical_flag = critical_count >= 2
        else:
            has_critical_flag = bool(critical_flags & set(self.quality_flags))
        return self.quality_score >= 0.6 and not hard and not has_critical_flag

    def _hard_invariant_violations(self) -> bool:
        """True if any hard (critical) invariant violation is present."""
        for v in self.invariant_violations:
            if v == "empty_grid":
                return True
            if "row_" in v and "col_count" in v:
                return True
            if "duplicate_periods" in v:
                return True
            if v.startswith("soft_anomaly:"):
                continue
            if "tblGrid_col_mismatch" in v or "vmerge_misalign" in v:
                continue
            if "exception:" in v:
                return True
        return False


class OOXMLTableGridExtractor:
    """
    Reconstruct table grid from OOXML (tblGrid, gridSpan, vMerge).
    Performs invariant checks and assigns quality_score in [0.0, 1.0].
    Threshold 0.6: below = consider fallback.
    """

    QUALITY_THRESHOLD = 0.6

    def extract(self, table: Any) -> ExtractionResult:
        """
        Extract grid from a python-docx Table.

        Args:
            table: docx.table.Table instance.

        Returns:
            ExtractionResult with grid, quality_score, quality_flags.
        """
        try:
            grid, cells, vmerge_violations, grid_span_count, vmerge_count = (
                self._reconstruct_grid(table)
            )
        except Exception as e:
            logger.warning("OOXML grid reconstruction failed: %s", e)
            return ExtractionResult(
                grid=[],
                quality_score=0.0,
                quality_flags=["extraction_failed"],
                invariant_violations=[f"exception: {e!s}"],
                failure_reason_code="EXTRACTION_FAILED",
            )

        if not grid:
            return ExtractionResult(
                grid=[],
                quality_score=0.0,
                quality_flags=["empty_grid"],
                failure_reason_code="EMPTY_GRID",
            )

        rows = len(grid)
        cols = max(len(r) for r in grid) if grid else 0
        expected_cols = self._get_tbl_grid_col_count(table)

        # P2: Normalize grid to expected_cols when tblGrid present and built cols differ
        if expected_cols is not None and cols != expected_cols:
            for r_idx, row in enumerate(grid):
                if len(row) < expected_cols:
                    grid[r_idx] = list(row) + [""] * (expected_cols - len(row))
                else:
                    grid[r_idx] = row[:expected_cols]
            cols = expected_cols

        invariant_violations = self._check_invariants(
            grid, rows, cols, expected_cols=expected_cols
        )
        invariant_violations = list(invariant_violations) + list(vmerge_violations)
        quality_score, quality_flags = self._score_quality(
            grid, rows, cols, invariant_violations
        )
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
            grid_cols_expected=expected_cols,
            grid_cols_built=cols,
            grid_span_count=grid_span_count,
            vmerge_count=vmerge_count,
        )

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

    def _reconstruct_grid(
        self, table: Any
    ) -> Tuple[List[List[str]], List[Cell], List[str], int, int]:
        """Reconstruct 2D grid from tblGrid + gridSpan/vMerge. R2: tblGrid-driven;
        placeholders empty; only root-cell holds text; soft anomalies when tblGrid missing or span exceeds.
        Returns (grid, cells, vmerge_violations, grid_span_count, vmerge_count).
        """
        expected_cols = self._get_tbl_grid_col_count(table)
        vmerge_violations: List[str] = []
        grid_span_count = 0
        vmerge_count = 0
        inferred_max = 0
        for row in table.rows:
            col_count = 0
            for cell in row.cells:
                span = self._get_grid_span(cell._element)
                if span > 1:
                    grid_span_count += 1
                if self._get_vmerge_val(cell._element) is not None:
                    vmerge_count += 1
                col_count += span
            inferred_max = max(inferred_max, col_count)

        if inferred_max == 0:
            return [], [], [], 0, 0

        # R2: Use tblGrid when present; else infer and record soft anomaly
        soft_anomalies: List[str] = []
        if expected_cols is not None:
            max_cols = max(expected_cols, inferred_max)
            if inferred_max > expected_cols:
                soft_anomalies.append("span_exceeds_tblGrid")
        else:
            max_cols = inferred_max
            soft_anomalies.append("tblGrid_missing")

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
                span = self._get_grid_span(cell_elem)
                v_val = self._get_vmerge_val(cell_elem)

                while col_ptr < max_cols and grid[r_idx][col_ptr] != "":
                    col_ptr += 1
                if col_ptr >= max_cols:
                    break

                # Ensure we have enough columns for this span
                if col_ptr + span > max_cols:
                    need = col_ptr + span - max_cols
                    for _ in range(need):
                        for r in grid:
                            r.append("")
                        active_vmerge.append(None)
                    max_cols = col_ptr + span
                    if "span_exceeds_tblGrid" not in soft_anomalies:
                        soft_anomalies.append("span_exceeds_tblGrid")

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

                # R2: Only root-cell holds text; placeholders stay empty
                if col_ptr < max_cols and final_text is not None:
                    grid[r_idx][col_ptr] = final_text
                    cells.append(
                        Cell(
                            row=r_idx,
                            col=col_ptr,
                            value=final_text,
                            col_span=span,
                            row_span=1,
                        )
                    )
                for i in range(1, span):
                    if col_ptr + i < max_cols:
                        grid[r_idx][col_ptr + i] = ""  # placeholder

                col_ptr += span

        all_violations = vmerge_violations + [
            f"soft_anomaly:{a}" for a in soft_anomalies
        ]
        return grid, cells, all_violations, grid_span_count, vmerge_count

    def _get_grid_span(self, cell_elem: Any) -> int:
        """Return gridSpan value (default 1). R2: gridSpan=0 or missing => 1."""
        gs = cell_elem.xpath(".//*[local-name()='gridSpan']")
        if not gs:
            return 1
        val = gs[0].get(f"{W_NS}val") or gs[0].get("val")
        if val is None:
            return 1
        try:
            n = int(val)
            return 1 if n <= 0 else n
        except (ValueError, TypeError):
            return 1

    def _get_vmerge_val(self, cell_elem: Any) -> Optional[str]:
        """Return vMerge value: 'restart', 'continue', or None."""
        vm = cell_elem.xpath(".//*[local-name()='vMerge']")
        if not vm:
            return None
        val = vm[0].get(f"{W_NS}val") or vm[0].get("val")
        if val is None:
            return "continue"
        s = str(val).strip().lower()
        if s in ("restart", "continue"):
            return s
        return "continue"

    def _derive_failure_reason_code(
        self,
        invariant_violations: List[str],
        quality_flags: List[str],
    ) -> Optional[str]:
        """Derive failure_reason_code only when grid cannot be reconciled.
        tblGrid_col_mismatch and vmerge_misalign are soft: WARN + invariant flag, no FAIL_TOOL_EXTRACT.
        """
        if "GRID_CORRUPTION" in quality_flags or any(
            v.startswith("row_") and "col_count" in v for v in invariant_violations
        ):
            return "GRID_CORRUPTION"
        if (
            "duplicate_periods" in invariant_violations
            or "DUPLICATE_PERIODS" in quality_flags
        ):
            return "DUPLICATE_PERIODS"
        return None

    @staticmethod
    def _is_period_like_header(cell_text: str) -> bool:
        """True if cell looks like a period/year header (e.g. 2020, FY2021, 31/12/2020).
        False for empty, Code, Note, Description, Item, Line.
        Strips trailing _[0-9]+ so duplicated headers (e.g. 31/12/2018_2) still match for period detection.
        """
        s = (cell_text or "").strip()
        if not s:
            return False
        s_base = re.sub(r"_[0-9]+$", "", s)
        if not s_base:
            return False
        if _CODE_NOTE_PATTERN.match(s_base):
            return False
        return bool(_PERIOD_YEAR_PATTERN.match(s_base))

    @staticmethod
    def _detect_caption_rows(grid: List[List[str]]) -> Set[int]:
        """Return row indices that look like caption (single non-empty cell or very low label density)."""
        caption: Set[int] = set()
        if not grid:
            return caption
        cols = len(grid[0]) if grid else 0
        for r, row in enumerate(grid):
            if len(row) != cols:
                continue
            non_empty = [c for c in row if str(c).strip()]
            if len(non_empty) <= 1:
                caption.add(r)
            elif len(non_empty) <= 2 and cols >= 3:
                # Very low density for a wide row
                caption.add(r)
        return caption

    def _check_invariants(
        self,
        grid: List[List[str]],
        rows: int,
        cols: int,
        expected_cols: Optional[int] = None,
    ) -> List[str]:
        """Check grid invariants; return list of violation messages."""
        try:
            from ...config.feature_flags import get_feature_flags

            v2 = get_feature_flags().get("extractor_usable_v2", False)
        except Exception:
            v2 = False

        violations: List[str] = []
        if rows == 0 or cols == 0:
            violations.append("empty_grid")
            return violations

        caption_rows: Set[int] = set()
        if v2:
            caption_rows = self._detect_caption_rows(grid)

        for r, row in enumerate(grid):
            if v2 and r in caption_rows:
                continue
            if len(row) != cols:
                violations.append(f"row_{r}_col_count_{len(row)}_expected_{cols}")

        if expected_cols is not None and cols != expected_cols:
            violations.append("tblGrid_col_mismatch")

        # Duplicate period columns: when v2 only among period-like header cells; header = first row with label density
        if grid and len(grid[0]) == cols:
            if v2:
                # Header row = first row with >= 2 non-empty, non-code/note cells
                header_row_idx = 0
                for r, row in enumerate(grid):
                    if r in caption_rows:
                        continue
                    labels = [
                        str(c).strip()
                        for c in row
                        if str(c).strip()
                        and not _CODE_NOTE_PATTERN.match(str(c).strip())
                    ]
                    if len(labels) >= 2:
                        header_row_idx = r
                        break
                header = [str(c).strip() for c in grid[header_row_idx]]
                # Detect duplicates by base period (strip _N suffix) so CY/PY mapping still sees canonical names
                period_bases = [
                    re.sub(r"_[0-9]+$", "", h).strip() or h
                    for h in header
                    if self._is_period_like_header(h)
                ]
                if len(period_bases) != len(set(period_bases)):
                    # Keep first occurrence unchanged; add suffix only to subsequent duplicates
                    seen_periods: dict[str, int] = {}
                    for col_idx in range(len(grid[header_row_idx])):
                        h = str(grid[header_row_idx][col_idx]).strip()
                        if not self._is_period_like_header(h):
                            continue
                        base = re.sub(r"_[0-9]+$", "", h).strip() or h
                        if base not in seen_periods:
                            seen_periods[base] = 1
                            grid[header_row_idx][col_idx] = base
                        else:
                            seen_periods[base] += 1
                            grid[header_row_idx][
                                col_idx
                            ] = f"{base}_{seen_periods[base]}"
                    violations.append("duplicate_periods_renamed")
            else:
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
        """
        R2: Compute quality_score in [0.0, 1.0] and quality_flags.
        Hard violations (empty_grid, row col_count, duplicate_periods) force score <= 0.55.
        Soft violations (tblGrid_col_mismatch, vmerge_misalign, soft_anomaly) reduce score but allow >= 0.6.
        """
        flags: List[str] = []
        score = 1.0
        has_hard = False

        if invariant_violations:
            if "empty_grid" in invariant_violations:
                return 0.0, ["empty_grid"]
            for v in invariant_violations:
                if v.startswith("row_") and "col_count" in v:
                    flags.append("GRID_CORRUPTION")
                    score -= 0.5
                    has_hard = True
                    break
            if "duplicate_periods" in invariant_violations:
                flags.append("DUPLICATE_PERIODS")
                score -= 0.5
                has_hard = True
            # R2 soft: tblGrid_col_mismatch and vmerge_misalign reduce score only
            if "tblGrid_col_mismatch" in invariant_violations:
                score -= 0.2
            if any("vmerge_misalign" in v for v in invariant_violations):
                score -= 0.2
            for v in invariant_violations:
                if v.startswith("soft_anomaly:"):
                    score -= 0.1
                    break

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
        # R2: Only hard violations force score below threshold
        if has_hard or {"GRID_CORRUPTION", "DUPLICATE_PERIODS"} & set(flags):
            score = min(score, 0.55)
        try:
            from ...config.feature_flags import get_feature_flags

            if get_feature_flags().get("extractor_usable_v2", False):
                logger.debug(
                    "extractor_usable_v2 _score_quality score=%.2f flags=%s",
                    score,
                    flags,
                )
        except Exception:
            pass
        return round(score, 2), flags
