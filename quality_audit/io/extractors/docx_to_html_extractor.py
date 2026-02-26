"""
LibreOffice fallback extractor: convert docx to HTML via LibreOffice CLI,
parse HTML table(s), return ExtractionResult with CONVERSION_FALLBACK flag.
Uses stdlib html.parser only.
"""

import contextlib
import logging
import os
import shutil
import subprocess
import tempfile
from html.parser import HTMLParser
from pathlib import Path
from typing import List, Optional, Tuple

from .ooxml_table_grid_extractor import Cell, ExtractionResult

logger = logging.getLogger(__name__)

QUALITY_THRESHOLD = 0.6


class _TableCollector(HTMLParser):
    """Collect first table's rows and cells from HTML."""

    def __init__(self) -> None:
        super().__init__()
        self._in_table = False
        self._in_row = False
        self._in_cell = False
        self._depth_table = 0
        self._depth_row = 0
        self._depth_cell = 0
        self._current_row: List[str] = []
        self._current_cell: List[str] = []
        self.rows: List[List[str]] = []

    def handle_starttag(self, tag: str, attrs: List[Tuple[str, Optional[str]]]) -> None:
        tag = tag.lower()
        if tag == "table":
            self._depth_table += 1
            if self._depth_table == 1:
                self._in_table = True
        elif self._in_table and tag == "tr":
            self._depth_row += 1
            if self._depth_row == 1:
                self._in_row = True
                self._current_row = []
        elif self._in_table and self._in_row and tag in ("td", "th"):
            self._depth_cell += 1
            if self._depth_cell == 1:
                self._in_cell = True
                self._current_cell = []

    def handle_endtag(self, tag: str) -> None:
        tag = tag.lower()
        if tag == "table":
            self._depth_table = max(0, self._depth_table - 1)
            if self._depth_table == 0:
                self._in_table = False
        elif tag == "tr":
            self._depth_row = max(0, self._depth_row - 1)
            if self._depth_row == 0 and self._in_row:
                self._in_row = False
                if self._current_row:
                    self.rows.append(self._current_row)
        elif tag in ("td", "th"):
            self._depth_cell = max(0, self._depth_cell - 1)
            if self._depth_cell == 0 and self._in_cell:
                self._in_cell = False
                text = " ".join(self._current_cell).strip()
                self._current_row.append(text)

    def handle_data(self, data: str) -> None:
        if self._in_cell:
            self._current_cell.append(data)


def _find_soffice() -> Optional[str]:
    """Locate soffice (LibreOffice) executable."""
    names = ["soffice", "soffice.exe"]
    for name in names:
        path = shutil.which(name)
        if path:
            return path
    if os.name == "nt":
        for base in (
            os.path.expandvars(r"%ProgramFiles%\LibreOffice\program"),
            os.path.expandvars(r"%ProgramFiles(x86)%\LibreOffice\program"),
        ):
            for name in names:
                p = os.path.join(base, name)
                if os.path.isfile(p):
                    return p
    return None


class DocxToHtmlExtractor:
    """
    Fallback extractor: convert docx to HTML via LibreOffice CLI,
    parse first table, return ExtractionResult with CONVERSION_FALLBACK.
    """

    def extract_from_path(self, docx_path: str) -> ExtractionResult:
        """
        Convert docx to HTML, parse first table, return ExtractionResult.

        Args:
            docx_path: Path to .docx file.

        Returns:
            ExtractionResult with grid, quality_score, quality_flags.
        """
        docx_path = os.path.abspath(docx_path)
        if not os.path.isfile(docx_path):
            return ExtractionResult(
                grid=[],
                quality_score=0.0,
                quality_flags=["file_not_found", "CONVERSION_FALLBACK"],
                invariant_violations=[f"path not found: {docx_path}"],
                failure_reason_code="CONVERSION_FAILED",
            )

        soffice = _find_soffice()
        if not soffice:
            logger.warning("LibreOffice (soffice) not found")
            return ExtractionResult(
                grid=[],
                quality_score=0.0,
                quality_flags=["soffice_not_found", "CONVERSION_FALLBACK"],
                failure_reason_code="CONVERSION_FAILED",
            )

        out_dir = tempfile.mkdtemp()
        try:
            cmd = [
                soffice,
                "--headless",
                "--convert-to",
                "html",
                "--outdir",
                out_dir,
                docx_path,
            ]
            result = subprocess.run(
                cmd,
                capture_output=True,
                text=True,
                timeout=60,
                cwd=out_dir,
            )
            if result.returncode != 0:
                logger.warning("LibreOffice conversion failed: %s", result.stderr)
                return ExtractionResult(
                    grid=[],
                    quality_score=0.0,
                    quality_flags=["conversion_failed", "CONVERSION_FALLBACK"],
                    invariant_violations=[result.stderr or "unknown error"],
                    failure_reason_code="CONVERSION_FAILED",
                )

            base = Path(docx_path).stem
            html_path = Path(out_dir) / f"{base}.html"
            if not html_path.exists():
                return ExtractionResult(
                    grid=[],
                    quality_score=0.0,
                    quality_flags=["html_not_created", "CONVERSION_FALLBACK"],
                    failure_reason_code="CONVERSION_FAILED",
                )

            with open(html_path, encoding="utf-8", errors="replace") as f:
                html_content = f.read()

            parser = _TableCollector()
            parser.feed(html_content)
            rows = parser.rows

        finally:
            with contextlib.suppress(OSError):
                shutil.rmtree(out_dir, ignore_errors=True)

        if not rows:
            return ExtractionResult(
                grid=[],
                quality_score=0.0,
                quality_flags=["no_table_in_html", "CONVERSION_FALLBACK"],
                failure_reason_code="NO_TABLE_IN_HTML",
            )

        cols = max(len(r) for r in rows) if rows else 0
        grid = []
        for r in rows:
            row = list(r)
            while len(row) < cols:
                row.append("")
            grid.append(row[:cols])

        rows_n, cols_n = len(grid), cols
        invariant_violations = _check_invariants(grid, rows_n, cols_n)
        quality_score, quality_flags = _score_quality(
            grid, rows_n, cols_n, invariant_violations
        )
        quality_flags = quality_flags or []
        quality_flags.append("CONVERSION_FALLBACK")
        failure_reason_code = _derive_failure_reason_code(
            invariant_violations, quality_flags
        )

        cells: List[Cell] = []
        for ri, row in enumerate(grid):
            for ci, val in enumerate(row):
                cells.append(
                    Cell(row=ri, col=ci, value=val or "", col_span=1, row_span=1)
                )

        return ExtractionResult(
            grid=grid,
            cells=cells,
            quality_score=quality_score,
            quality_flags=quality_flags,
            rows=rows_n,
            cols=cols_n,
            invariant_violations=invariant_violations,
            failure_reason_code=failure_reason_code,
        )


def _derive_failure_reason_code(
    invariant_violations: List[str],
    quality_flags: List[str],
) -> Optional[str]:
    """Derive failure_reason_code from invariant_violations and quality_flags."""
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


def _check_invariants(grid: List[List[str]], rows: int, cols: int) -> List[str]:
    """Check grid invariants; return list of violation messages."""
    violations: List[str] = []
    if rows == 0 or cols == 0:
        violations.append("empty_grid")
        return violations
    for r, row in enumerate(grid):
        if len(row) != cols:
            violations.append(f"row_{r}_col_count_{len(row)}_expected_{cols}")
    if grid and len(grid[0]) == cols:
        header = [str(c).strip() for c in grid[0]]
        if len(header) != len(set(header)):
            violations.append("duplicate_periods")
    return violations


def _score_quality(
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
            score -= 0.3
        for v in invariant_violations:
            if v.startswith("row_") and "col_count" in v:
                flags.append("GRID_CORRUPTION")
                score -= 0.5
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
    if {"GRID_CORRUPTION", "DUPLICATE_PERIODS"} & set(flags):
        score = min(score, 0.55)
    return round(score, 2), flags
