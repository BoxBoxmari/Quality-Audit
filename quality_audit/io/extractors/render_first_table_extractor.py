"""
Render-first table extractor.
Orchestrates the full pipeline: isolate → convert → render → structure → OCR → map → gate.
"""

import json
import logging
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

import numpy as np

from .conversion import FallbackConverter
from .ocr import OCRResult, OCRToken, get_best_ocr_engine
from .structure import BaselineGridRecognizer, CellBox, StructureResult
from .table_isolator import TableIsolator
from .token_mapper import (
    CellContent,
    TokenToCellMapper,
    build_grid_from_cell_contents,
)

logger = logging.getLogger(__name__)


# Quality gating thresholds (from constants.py equivalent)
RENDER_FIRST_THRESHOLDS = {
    "auto_accept": {
        "token_coverage_ratio": 0.9,
        "mean_cell_confidence": 0.85,
        "p10_cell_confidence": 0.7,
        "empty_cell_ratio_max": 0.3,
    },
    "warn": {
        "token_coverage_ratio": 0.7,
        "mean_cell_confidence": 0.7,
        "p10_cell_confidence": 0.5,
        "empty_cell_ratio_max": 0.5,
    },
}


@dataclass
class QualityMetrics:
    """Quality metrics for render-first extraction."""

    token_coverage_ratio: float = 0.0
    empty_cell_ratio: float = 0.0
    mean_cell_confidence: float = 0.0
    p10_cell_confidence: float = 0.0
    numeric_parse_success_ratio: float = 0.0
    total_tokens: int = 0
    assigned_tokens: int = 0
    total_cells: int = 0
    empty_cells: int = 0
    numeric_cells: int = 0
    structural_sanity: bool = True
    sanity_issues: List[str] = field(default_factory=list)

    def to_dict(self) -> Dict[str, Any]:
        return {
            "token_coverage_ratio": self.token_coverage_ratio,
            "empty_cell_ratio": self.empty_cell_ratio,
            "mean_cell_confidence": self.mean_cell_confidence,
            "p10_cell_confidence": self.p10_cell_confidence,
            "numeric_parse_success_ratio": self.numeric_parse_success_ratio,
            "total_tokens": self.total_tokens,
            "assigned_tokens": self.assigned_tokens,
            "total_cells": self.total_cells,
            "empty_cells": self.empty_cells,
            "numeric_cells": self.numeric_cells,
            "structural_sanity": self.structural_sanity,
            "sanity_issues": self.sanity_issues,
        }


@dataclass
class RenderFirstExtractionResult:
    """Result of render-first extraction with full telemetry."""

    grid: List[List[str]]
    cells: List[CellBox] = field(default_factory=list)
    quality_score: float = 0.0
    quality_flags: List[str] = field(default_factory=list)
    is_usable: bool = False
    failure_reason_code: Optional[str] = None

    # Telemetry
    conversion_mode: Optional[str] = None
    structure_recognizer: Optional[str] = None
    ocr_engine: Optional[str] = None

    # Ticket 1: Extraction quality metadata
    extraction_engine: str = "ooxml_fallback"  # default; overridden on success
    extraction_confidence: float = 0.0

    # Metrics
    token_coverage_ratio: Optional[float] = None
    mean_cell_confidence: Optional[float] = None
    p10_cell_confidence: Optional[float] = None
    empty_cell_ratio: Optional[float] = None
    rows: int = 0
    cols: int = 0

    # Debug
    debug_artifact_path: Optional[str] = None
    rejection_reason: Optional[str] = None

    def to_extraction_result_dict(self) -> Dict[str, Any]:
        """Convert to dict compatible with existing ExtractionResult interface."""
        return {
            "grid": self.grid,
            "quality_score": self.quality_score,
            "quality_flags": list(self.quality_flags),
            "is_usable": self.is_usable,
            "failure_reason_code": self.failure_reason_code,
            "rows": self.rows,
            "cols": self.cols,
            "extraction_engine": self.extraction_engine,
            "extraction_confidence": self.extraction_confidence,
        }


class RenderFirstTableExtractor:
    """
    Render-first table extraction engine.

    Pipeline:
    1. Isolate table to temporary DOCX
    2. Convert DOCX to PDF via LibreOffice (local soffice)
    3. Render PDF page to image
    4. Detect table structure (cells, rows, cols)
    5. Extract text via OCR
    6. Map tokens to cells
    7. Compute quality metrics
    8. Gate acceptance based on confidence
    """

    def __init__(
        self,
        dpi: int = 300,
        save_debug_artifacts: bool = True,
        debug_artifact_dir: Optional[str] = None,
    ):
        """
        Initialize the render-first extractor.

        Args:
            dpi: Resolution for PDF rendering.
            save_debug_artifacts: Whether to save debug artifacts on failure.
            debug_artifact_dir: Directory for debug artifacts.
        """
        self.dpi = dpi
        self.save_debug_artifacts = save_debug_artifacts
        self.debug_artifact_dir = debug_artifact_dir

        self._converter = FallbackConverter()
        self._isolator = TableIsolator(dpi=dpi)
        self._structure_recognizer = self._get_best_structure_recognizer()
        self._ocr_engine = get_best_ocr_engine()
        self._token_mapper = TokenToCellMapper()

    def is_available(self) -> bool:
        """
        Check if render-first pipeline can run (system binaries present).

        Requires local soffice for DOCX→PDF. If False, callers should skip
        render-first and use legacy fallback without calling extract().
        """
        return self._converter.is_available()

    def _get_best_structure_recognizer(self):
        """
        Select the best available structure recognizer.

        Prefers TableTransformerRecognizer if available (requires torch + transformers),
        otherwise falls back to BaselineGridRecognizer.
        """
        try:
            from .structure import TableTransformerRecognizer

            if TableTransformerRecognizer.is_available():
                logger.info("Using TableTransformerRecognizer (advanced)")
                return TableTransformerRecognizer()
        except ImportError:
            pass

        logger.info("Using BaselineGridRecognizer (fallback)")
        return BaselineGridRecognizer()

    def extract(
        self,
        table: Any,  # docx.table.Table
        file_path: str,
        table_index: int,
    ) -> RenderFirstExtractionResult:
        """
        Extract table using render-first pipeline.

        Args:
            table: python-docx Table object.
            file_path: Path to source DOCX file.
            table_index: Index of table in document.

        Returns:
            RenderFirstExtractionResult with grid and metadata.
        """
        result = RenderFirstExtractionResult(grid=[])

        if not self._converter.is_available():
            result.failure_reason_code = "RENDER_FIRST_SKIPPED_BINARIES_MISSING"
            result.rejection_reason = "soffice not found"
            logger.debug("Render-first skipped: system binaries missing (soffice)")
            return result

        try:
            # Step 1-3: Isolate, convert, render
            image, conversion_mode, error = self._isolator.isolate_and_render(
                table, self._converter
            )

            result.conversion_mode = conversion_mode

            if image is None:
                result.failure_reason_code = "RENDER_FIRST_CONVERSION_FAILED"
                result.rejection_reason = error
                # Ticket 1: Structured warning on fallback
                logger.warning(
                    "EXTRACTION_FALLBACK: engine=ooxml_fallback reason=%s", error
                )
                return result

            # Step 4: Detect structure
            structure_result = self._structure_recognizer.detect_cells(image)
            result.structure_recognizer = structure_result.recognizer_type

            if not structure_result.is_valid:
                result.failure_reason_code = "RENDER_FIRST_STRUCTURE_FAILED"
                result.rejection_reason = structure_result.error or "No cells detected"
                logger.warning(
                    "Render-first structure detection failed: %s",
                    structure_result.error,
                )
                return result

            # Step 5: OCR
            ocr_result = self._ocr_engine.extract_tokens(image)
            result.ocr_engine = ocr_result.engine_type

            if not ocr_result.is_valid:
                result.failure_reason_code = "RENDER_FIRST_OCR_FAILED"
                result.rejection_reason = ocr_result.error or "OCR failed"
                logger.warning("Render-first OCR failed: %s", ocr_result.error)
                return result

            # Step 6: Map tokens to cells
            cell_contents = self._token_mapper.map_tokens_to_cells(
                ocr_result.tokens, structure_result.cells
            )

            # Step 7: Compute quality metrics
            metrics = self._compute_quality_metrics(
                cell_contents,
                ocr_result.tokens,
                structure_result,
            )

            # Step 8: Gate acceptance
            is_usable, quality_score, quality_flags, failure_reason = (
                self._gate_acceptance(metrics)
            )

            # Build final grid
            grid = build_grid_from_cell_contents(
                cell_contents,
                structure_result.num_rows,
                structure_result.num_cols,
            )

            result.grid = grid
            result.cells = structure_result.cells
            result.is_usable = is_usable
            result.quality_score = quality_score
            result.quality_flags = quality_flags
            result.failure_reason_code = failure_reason
            result.rows = structure_result.num_rows
            result.cols = structure_result.num_cols

            # Ticket 1: Set extraction quality metadata on success
            result.extraction_engine = "render_first"
            result.extraction_confidence = quality_score

            # Set metrics
            result.token_coverage_ratio = metrics.token_coverage_ratio
            result.mean_cell_confidence = metrics.mean_cell_confidence
            result.p10_cell_confidence = metrics.p10_cell_confidence
            result.empty_cell_ratio = metrics.empty_cell_ratio

            # Save debug artifacts if needed
            if self.save_debug_artifacts and (not is_usable or quality_score < 0.8):
                artifact_path = self._save_debug_artifacts(
                    image=image,
                    structure_result=structure_result,
                    ocr_result=ocr_result,
                    cell_contents=cell_contents,
                    metrics=metrics,
                    grid=grid,
                    file_path=file_path,
                    table_index=table_index,
                )
                result.debug_artifact_path = artifact_path

            return result

        except Exception as e:
            logger.exception("Render-first extraction failed: %s", e)
            result.failure_reason_code = "RENDER_FIRST_EXCEPTION"
            result.rejection_reason = str(e)
            return result

    def _compute_quality_metrics(
        self,
        cell_contents: Dict[Tuple[int, int], CellContent],
        all_tokens: List[OCRToken],
        structure_result: StructureResult,
    ) -> QualityMetrics:
        """Compute quality metrics for the extraction."""
        metrics = QualityMetrics()

        # Token coverage
        metrics.total_tokens = len(all_tokens)
        assigned_token_count = sum(c.token_count for c in cell_contents.values())
        metrics.assigned_tokens = assigned_token_count
        if metrics.total_tokens > 0:
            metrics.token_coverage_ratio = assigned_token_count / metrics.total_tokens
        else:
            metrics.token_coverage_ratio = 0.0

        # Cell statistics
        metrics.total_cells = len(cell_contents)
        metrics.empty_cells = sum(1 for c in cell_contents.values() if c.is_empty)
        if metrics.total_cells > 0:
            metrics.empty_cell_ratio = metrics.empty_cells / metrics.total_cells
        else:
            metrics.empty_cell_ratio = 1.0

        # Confidence statistics
        confidences = [
            c.confidence for c in cell_contents.values() if c.token_count > 0
        ]
        if confidences:
            metrics.mean_cell_confidence = sum(confidences) / len(confidences)
            sorted_conf = sorted(confidences)
            p10_idx = max(0, int(len(sorted_conf) * 0.1))
            metrics.p10_cell_confidence = sorted_conf[p10_idx]
        else:
            metrics.mean_cell_confidence = 0.0
            metrics.p10_cell_confidence = 0.0

        # Numeric parse success
        numeric_count = 0
        parseable_count = 0
        for cell in cell_contents.values():
            if cell.text.strip():
                if self._is_numeric_like(cell.text):
                    numeric_count += 1
                parseable_count += 1

        metrics.numeric_cells = numeric_count
        if parseable_count > 0:
            metrics.numeric_parse_success_ratio = numeric_count / parseable_count
        else:
            metrics.numeric_parse_success_ratio = 0.0

        # Structural sanity
        metrics.structural_sanity = True
        metrics.sanity_issues = []

        # Check for extreme dimensions
        if structure_result.num_rows > 100:
            metrics.sanity_issues.append(f"too_many_rows:{structure_result.num_rows}")
        if structure_result.num_cols > 50:
            metrics.sanity_issues.append(f"too_many_cols:{structure_result.num_cols}")
        if structure_result.num_rows < 1 or structure_result.num_cols < 1:
            metrics.sanity_issues.append("invalid_dimensions")
            metrics.structural_sanity = False

        return metrics

    def _is_numeric_like(self, text: str) -> bool:
        """Check if text looks like a number (including formatted numbers)."""
        # Remove common formatting characters
        cleaned = text.replace(",", "").replace(".", "").replace(" ", "")
        cleaned = cleaned.replace("(", "").replace(")", "").replace("-", "")
        cleaned = cleaned.replace("%", "").replace("$", "").replace("₫", "")
        return cleaned.isdigit() if cleaned else False

    def _gate_acceptance(
        self, metrics: QualityMetrics
    ) -> Tuple[bool, float, List[str], Optional[str]]:
        """
        Gate acceptance based on quality metrics.

        Returns:
            Tuple of (is_usable, quality_score, quality_flags, failure_reason_code).
        """
        thresholds = RENDER_FIRST_THRESHOLDS

        quality_flags = []
        failure_reason = None

        # Check for structural issues
        if not metrics.structural_sanity:
            return (
                False,
                0.0,
                ["STRUCTURAL_SANITY_FAILED"],
                "RENDER_FIRST_STRUCTURAL_FAILURE",
            )

        # Check auto-accept thresholds
        auto_accept = thresholds["auto_accept"]
        if (
            metrics.token_coverage_ratio >= auto_accept["token_coverage_ratio"]
            and metrics.mean_cell_confidence >= auto_accept["mean_cell_confidence"]
            and metrics.p10_cell_confidence >= auto_accept["p10_cell_confidence"]
            and metrics.empty_cell_ratio <= auto_accept["empty_cell_ratio_max"]
        ):
            quality_score = 0.9 + 0.1 * metrics.mean_cell_confidence
            return (True, quality_score, [], None)

        # Check warn thresholds
        warn = thresholds["warn"]
        if (
            metrics.token_coverage_ratio >= warn["token_coverage_ratio"]
            and metrics.mean_cell_confidence >= warn["mean_cell_confidence"]
            and metrics.p10_cell_confidence >= warn["p10_cell_confidence"]
            and metrics.empty_cell_ratio <= warn["empty_cell_ratio_max"]
        ):
            quality_score = 0.6 + 0.3 * metrics.mean_cell_confidence
            quality_flags.append("BORDERLINE_CONFIDENCE")
            return (True, quality_score, quality_flags, None)

        # Below warn thresholds - not usable
        quality_score = 0.3 + 0.3 * metrics.mean_cell_confidence
        quality_flags.append("LOW_CONFIDENCE")

        # Determine specific failure reason
        if metrics.token_coverage_ratio < warn["token_coverage_ratio"]:
            failure_reason = "RENDER_FIRST_LOW_TOKEN_COVERAGE"
        elif metrics.mean_cell_confidence < warn["mean_cell_confidence"]:
            failure_reason = "RENDER_FIRST_LOW_CONFIDENCE"
        elif metrics.empty_cell_ratio > warn["empty_cell_ratio_max"]:
            failure_reason = "RENDER_FIRST_TOO_MANY_EMPTY_CELLS"
        else:
            failure_reason = "RENDER_FIRST_UNTRUSTED"

        return (False, quality_score, quality_flags, failure_reason)

    def _save_debug_artifacts(
        self,
        image: np.ndarray,
        structure_result: StructureResult,
        ocr_result: OCRResult,
        cell_contents: Dict[Tuple[int, int], CellContent],
        metrics: QualityMetrics,
        grid: List[List[str]],
        file_path: str,
        table_index: int,
    ) -> Optional[str]:
        """Save debug artifacts for analysis."""
        try:
            # Determine artifact directory
            if self.debug_artifact_dir:
                base_dir = Path(self.debug_artifact_dir)
            else:
                base_dir = Path("reports/debug_artifacts")

            # Create table-specific directory
            source_name = Path(file_path).stem
            artifact_dir = base_dir / source_name / f"table_{table_index}"
            artifact_dir.mkdir(parents=True, exist_ok=True)

            # Save image
            try:
                from PIL import Image as PILImage

                pil_image = PILImage.fromarray(image)
                pil_image.save(str(artifact_dir / "table.png"))
            except ImportError:
                pass

            # Save cell boxes JSON
            cell_boxes_data = [
                {
                    "row": c.row,
                    "col": c.col,
                    "x1": c.x1,
                    "y1": c.y1,
                    "x2": c.x2,
                    "y2": c.y2,
                    "row_span": c.row_span,
                    "col_span": c.col_span,
                }
                for c in structure_result.cells
            ]
            with open(artifact_dir / "cell_boxes.json", "w", encoding="utf-8") as f:
                json.dump(cell_boxes_data, f, indent=2)

            # Save OCR tokens JSON
            tokens_data = [
                {
                    "text": t.text,
                    "x1": t.x1,
                    "y1": t.y1,
                    "x2": t.x2,
                    "y2": t.y2,
                    "confidence": t.confidence,
                }
                for t in ocr_result.tokens
            ]
            with open(artifact_dir / "ocr_tokens.json", "w", encoding="utf-8") as f:
                json.dump(tokens_data, f, indent=2)

            # Save reconstructed CSV
            import csv

            with open(
                artifact_dir / "reconstructed.csv", "w", encoding="utf-8", newline=""
            ) as f:
                writer = csv.writer(f)
                for row in grid:
                    writer.writerow(row)

            # Save metrics JSON
            with open(artifact_dir / "metrics.json", "w", encoding="utf-8") as f:
                json.dump(metrics.to_dict(), f, indent=2)

            logger.info("Debug artifacts saved to: %s", artifact_dir)
            return str(artifact_dir)

        except Exception as e:
            logger.warning("Failed to save debug artifacts: %s", e)
            return None
