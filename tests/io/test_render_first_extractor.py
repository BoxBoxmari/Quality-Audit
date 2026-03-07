"""
Comprehensive unit tests for render-first table extraction pipeline.

Comment 2: Tests for conversion/OCR/mapping/gating with mocked dependencies.
Tests pipeline steps: isolate → render → structure → OCR → map → gate.
"""

from __future__ import annotations

from unittest.mock import MagicMock, patch

import numpy as np
import pytest

from quality_audit.io.extractors.ocr import OCRResult, OCRToken
from quality_audit.io.extractors.render_first_table_extractor import (
    QualityMetrics,
    RenderFirstExtractionResult,
    RenderFirstTableExtractor,
)
from quality_audit.io.extractors.structure import CellBox, StructureResult
from quality_audit.io.extractors.token_mapper import (
    CellContent,
    TokenToCellMapper,
    build_grid_from_cell_contents,
)

# Mark all tests in this module
pytestmark = pytest.mark.render_first


# =============================================================================
# Fixtures
# =============================================================================
@pytest.fixture
def mock_table():
    """Create a mock python-docx Table."""
    table = MagicMock()
    table.rows = [MagicMock(), MagicMock(), MagicMock()]
    for row in table.rows:
        row.cells = [MagicMock(), MagicMock(), MagicMock()]
    return table


@pytest.fixture
def simple_table_image() -> np.ndarray:
    """Generate a simple 3x3 table image (white bg, black lines)."""
    img = np.ones((150, 300, 3), dtype=np.uint8) * 255
    # Horizontal lines
    for y in [0, 50, 100, 149]:
        img[y, :, :] = 0
    # Vertical lines
    for x in [0, 100, 200, 299]:
        img[:, x, :] = 0
    return img


@pytest.fixture
def sample_cells_3x3() -> list[CellBox]:
    """3x3 grid of cells."""
    cells = []
    for r in range(3):
        for c in range(3):
            cells.append(
                CellBox(
                    row=r,
                    col=c,
                    x1=c * 100,
                    y1=r * 50,
                    x2=(c + 1) * 100,
                    y2=(r + 1) * 50,
                    confidence=0.9,
                )
            )
    return cells


@pytest.fixture
def sample_ocr_tokens() -> list[OCRToken]:
    """OCR tokens for 3x3 table."""
    return [
        OCRToken(text="Header1", x1=10, y1=10, x2=90, y2=40, confidence=0.95),
        OCRToken(text="Header2", x1=110, y1=10, x2=190, y2=40, confidence=0.93),
        OCRToken(text="Header3", x1=210, y1=10, x2=290, y2=40, confidence=0.91),
        OCRToken(text="100", x1=10, y1=60, x2=90, y2=90, confidence=0.88),
        OCRToken(text="200", x1=110, y1=60, x2=190, y2=90, confidence=0.87),
        OCRToken(text="300", x1=210, y1=60, x2=290, y2=90, confidence=0.89),
        OCRToken(text="Total", x1=10, y1=110, x2=90, y2=140, confidence=0.92),
        OCRToken(text="400", x1=110, y1=110, x2=190, y2=140, confidence=0.85),
        OCRToken(text="500", x1=210, y1=110, x2=290, y2=140, confidence=0.86),
    ]


# =============================================================================
# Test: Token-to-Cell Mapping
# =============================================================================
class TestTokenToCellMapper:
    """Tests for TokenToCellMapper."""

    @pytest.fixture
    def mapper(self) -> TokenToCellMapper:
        return TokenToCellMapper()

    def test_map_tokens_to_cells_basic(
        self,
        mapper: TokenToCellMapper,
        sample_cells_3x3: list[CellBox],
        sample_ocr_tokens: list[OCRToken],
    ):
        """Test basic token-to-cell mapping."""
        cell_contents = mapper.map_tokens_to_cells(sample_ocr_tokens, sample_cells_3x3)

        assert len(cell_contents) == 9
        texts = {(c.row, c.col): c.text for c in cell_contents.values()}
        assert texts[(0, 0)] == "Header1"
        assert texts[(1, 1)] == "200"
        assert texts[(2, 0)] == "Total"

    def test_map_tokens_empty_cells(
        self, mapper: TokenToCellMapper, sample_cells_3x3: list[CellBox]
    ):
        """Test mapping with no tokens results in empty cells."""
        cell_contents = mapper.map_tokens_to_cells([], sample_cells_3x3)
        assert len(cell_contents) == 9
        for c in cell_contents.values():
            assert c.text == ""

    def test_token_outside_cells_ignored(
        self, mapper: TokenToCellMapper, sample_cells_3x3: list[CellBox]
    ):
        """Test that tokens outside all cells are ignored."""
        tokens = [
            OCRToken(text="Outside", x1=500, y1=500, x2=600, y2=600, confidence=0.9)
        ]
        cell_contents = mapper.map_tokens_to_cells(tokens, sample_cells_3x3)
        for c in cell_contents.values():
            assert c.text == ""

    def test_multiple_tokens_same_cell(
        self, mapper: TokenToCellMapper, sample_cells_3x3: list[CellBox]
    ):
        """Test that multiple tokens in same cell are concatenated."""
        tokens = [
            OCRToken(text="First", x1=10, y1=10, x2=40, y2=40, confidence=0.9),
            OCRToken(text="Second", x1=50, y1=10, x2=90, y2=40, confidence=0.9),
        ]
        cell_contents = mapper.map_tokens_to_cells(tokens, sample_cells_3x3)
        content_00 = next(
            c for c in cell_contents.values() if c.row == 0 and c.col == 0
        )
        assert "First" in content_00.text
        assert "Second" in content_00.text


# =============================================================================
# Test: Build Grid from Cell Contents
# =============================================================================
class TestBuildGridFromCellContents:
    """Tests for build_grid_from_cell_contents."""

    def test_basic_grid_construction(self):
        """Test building a 2x2 grid."""
        cell_contents = {
            (0, 0): CellContent(0, 0, "A", 0.9, 1),
            (0, 1): CellContent(0, 1, "B", 0.9, 1),
            (1, 0): CellContent(1, 0, "C", 0.9, 1),
            (1, 1): CellContent(1, 1, "D", 0.9, 1),
        }
        grid = build_grid_from_cell_contents(cell_contents, num_rows=2, num_cols=2)
        assert grid == [["A", "B"], ["C", "D"]]

    def test_sparse_grid_fills_empty(self):
        """Test that missing cells are filled with empty strings."""
        cell_contents = {(0, 0): CellContent(0, 0, "Only", 0.9, 1)}
        grid = build_grid_from_cell_contents(cell_contents, num_rows=2, num_cols=2)
        assert grid == [["Only", ""], ["", ""]]

    def test_spanning_cells(self):
        """Test grid with merged first cell (one cell content, rest empty)."""
        cell_contents = {
            (0, 0): CellContent(0, 0, "Merged", 0.9, 1),
            (1, 0): CellContent(1, 0, "A", 0.9, 1),
            (1, 1): CellContent(1, 1, "B", 0.9, 1),
        }
        grid = build_grid_from_cell_contents(cell_contents, num_rows=2, num_cols=2)
        assert grid[0][0] == "Merged"
        assert grid[1] == ["A", "B"]


# =============================================================================
# Test: Quality Gating (4 cases: auto-accept, warn, fail, edge cases)
# =============================================================================
class TestQualityGating:
    """Tests for quality gating logic."""

    @pytest.fixture
    def extractor(self) -> RenderFirstTableExtractor:
        with patch.object(
            RenderFirstTableExtractor, "_get_best_structure_recognizer"
        ) as mock:
            mock.return_value = MagicMock()
            return RenderFirstTableExtractor(save_debug_artifacts=False)

    def test_auto_accept_high_quality(self, extractor: RenderFirstTableExtractor):
        """Test auto-accept when all metrics exceed thresholds."""
        metrics = QualityMetrics(
            token_coverage_ratio=0.95,
            mean_cell_confidence=0.90,
            p10_cell_confidence=0.75,
            empty_cell_ratio=0.1,
        )
        is_usable, score, flags, reason = extractor._gate_acceptance(metrics)
        assert is_usable is True
        assert score >= 0.9
        assert "BORDERLINE_CONFIDENCE" not in flags
        assert reason is None

    def test_warn_borderline_quality(self, extractor: RenderFirstTableExtractor):
        """Test borderline confidence triggers WARN flag."""
        metrics = QualityMetrics(
            token_coverage_ratio=0.75,
            mean_cell_confidence=0.72,
            p10_cell_confidence=0.55,
            empty_cell_ratio=0.4,
        )
        is_usable, score, flags, reason = extractor._gate_acceptance(metrics)
        assert is_usable is True
        assert "BORDERLINE_CONFIDENCE" in flags
        assert 0.6 <= score < 0.9

    def test_fail_low_coverage(self, extractor: RenderFirstTableExtractor):
        """Test low coverage fails extraction."""
        metrics = QualityMetrics(
            token_coverage_ratio=0.5,
            mean_cell_confidence=0.60,
            p10_cell_confidence=0.40,
            empty_cell_ratio=0.6,
        )
        is_usable, score, flags, reason = extractor._gate_acceptance(metrics)
        assert is_usable is False
        assert reason is not None

    def test_fail_low_confidence(self, extractor: RenderFirstTableExtractor):
        """Test low confidence fails extraction."""
        metrics = QualityMetrics(
            token_coverage_ratio=0.8,
            mean_cell_confidence=0.50,  # Below threshold
            p10_cell_confidence=0.30,
            empty_cell_ratio=0.2,
        )
        is_usable, score, flags, reason = extractor._gate_acceptance(metrics)
        assert is_usable is False


# =============================================================================
# Test: Converter (local soffice only)
# =============================================================================
class TestConverterSelection:
    """Tests for converter (local soffice only)."""

    def test_fallback_converter_instantiation(self):
        """Test that FallbackConverter can be instantiated."""
        from quality_audit.io.extractors.conversion import FallbackConverter

        converter = FallbackConverter()
        assert converter is not None

    def test_conversion_mode_reported_in_result(self):
        """Test that conversion_mode is reported in extraction result."""
        result = RenderFirstExtractionResult(
            grid=[["A"]],
            conversion_mode="local",
            is_usable=True,
        )
        assert result.conversion_mode == "local"


# =============================================================================
# Test: Structure Recognizer Selection
# =============================================================================
class TestStructureRecognizerSelection:
    """Tests for structure recognizer selection logic."""

    def test_baseline_grid_fallback_when_no_torch(self):
        """Test that BaselineGridRecognizer is used when TableTransformer unavailable."""
        with patch(
            "quality_audit.io.extractors.structure.table_transformer."
            "_check_table_transformer_available",
            return_value=False,
        ):
            extractor = RenderFirstTableExtractor(save_debug_artifacts=False)
            assert "baseline" in type(extractor._structure_recognizer).__name__.lower()


# =============================================================================
# Test: End-to-End Extraction (Mocked)
# =============================================================================
class TestRenderFirstExtractorE2E:
    """End-to-end tests with mocked dependencies."""

    @pytest.mark.parametrize("conversion_mode", ["local", "word_com"])
    def test_successful_extraction_full_pipeline(
        self,
        mock_table,
        simple_table_image: np.ndarray,
        sample_cells_3x3: list[CellBox],
        sample_ocr_tokens: list[OCRToken],
        conversion_mode: str,
    ):
        """Test successful end-to-end extraction with mocks for both backends."""
        with patch(
            "quality_audit.io.extractors.render_first_table_extractor.TableIsolator"
        ) as mock_isolator_cls, patch(
            "quality_audit.io.extractors.render_first_table_extractor."
            "get_best_ocr_engine"
        ) as mock_ocr_factory:
            # Setup mocks
            mock_isolator = MagicMock()
            mock_isolator.isolate_and_render.return_value = (
                simple_table_image,
                conversion_mode,
                None,
            )
            mock_isolator_cls.return_value = mock_isolator

            mock_ocr = MagicMock()
            mock_ocr.extract_tokens.return_value = OCRResult(
                tokens=sample_ocr_tokens,
                engine_type="tesseract",
                mean_confidence=0.90,
            )
            mock_ocr_factory.return_value = mock_ocr

            # Create extractor with mocked structure recognizer and converter
            extractor = RenderFirstTableExtractor(save_debug_artifacts=False)
            extractor._converter = MagicMock()
            extractor._converter.is_available.return_value = True
            extractor._structure_recognizer = MagicMock()
            extractor._structure_recognizer.detect_cells.return_value = StructureResult(
                cells=sample_cells_3x3,
                num_rows=3,
                num_cols=3,
                recognizer_type="baseline_grid",
                confidence=0.9,
            )

            # Run extraction
            result = extractor.extract(mock_table, "/path/to/doc.docx", 0)

            # Verify
            assert result.conversion_mode == conversion_mode
            assert result.ocr_engine == "tesseract"
            assert result.rows == 3
            assert result.cols == 3
            assert len(result.grid) == 3

    @pytest.mark.skipif(
        not __import__(
            "quality_audit.io.extractors.conversion",
            fromlist=["WordComConverter"],
        )
        .WordComConverter()
        .is_available(),
        reason="Word COM converter not available",
    )
    def test_render_first_integration_word_com_mode_reported(
        self,
        mock_table,
        simple_table_image: np.ndarray,
        sample_cells_3x3: list[CellBox],
        sample_ocr_tokens: list[OCRToken],
    ):
        """
        Integration-style test: when conversion backend reports 'word_com',
        the render-first pipeline should propagate that conversion_mode.
        """
        from quality_audit.io.extractors.conversion import FallbackConverter

        with patch(
            "quality_audit.io.extractors.render_first_table_extractor.TableIsolator"
        ) as mock_isolator_cls, patch(
            "quality_audit.io.extractors.render_first_table_extractor."
            "get_best_ocr_engine"
        ) as mock_ocr_factory:
            mock_isolator = MagicMock()
            mock_isolator.isolate_and_render.return_value = (
                simple_table_image,
                "word_com",
                None,
            )
            mock_isolator_cls.return_value = mock_isolator

            mock_ocr = MagicMock()
            mock_ocr.extract_tokens.return_value = OCRResult(
                tokens=sample_ocr_tokens,
                engine_type="tesseract",
                mean_confidence=0.90,
            )
            mock_ocr_factory.return_value = mock_ocr

            extractor = RenderFirstTableExtractor(save_debug_artifacts=False)
            extractor._converter = FallbackConverter()
            extractor._structure_recognizer = MagicMock()
            extractor._structure_recognizer.detect_cells.return_value = StructureResult(
                cells=sample_cells_3x3,
                num_rows=3,
                num_cols=3,
                recognizer_type="baseline_grid",
                confidence=0.9,
            )

            result = extractor.extract(mock_table, "/path/to/doc.docx", 0)

            assert result.conversion_mode == "word_com"

    def test_conversion_failure_returns_error(self, mock_table):
        """Test that conversion failure returns proper error result."""
        with patch(
            "quality_audit.io.extractors.render_first_table_extractor.TableIsolator"
        ) as mock_isolator_cls:
            mock_isolator = MagicMock()
            mock_isolator.isolate_and_render.return_value = (
                None,
                "unavailable",
                "soffice not found",
            )
            mock_isolator_cls.return_value = mock_isolator

            extractor = RenderFirstTableExtractor(save_debug_artifacts=False)
            # Ensure converter reports available so isolate_and_render is called
            extractor._converter = MagicMock()
            extractor._converter.is_available.return_value = True
            result = extractor.extract(mock_table, "/path/to/doc.docx", 0)

            assert result.is_usable is False
            assert result.failure_reason_code == "RENDER_FIRST_CONVERSION_FAILED"
            assert "soffice" in (result.rejection_reason or "")

    def test_ocr_failure_returns_error(
        self,
        mock_table,
        simple_table_image: np.ndarray,
        sample_cells_3x3: list[CellBox],
    ):
        """Test that OCR failure returns proper error result."""
        with patch(
            "quality_audit.io.extractors.render_first_table_extractor.TableIsolator"
        ) as mock_isolator_cls, patch(
            "quality_audit.io.extractors.render_first_table_extractor."
            "get_best_ocr_engine"
        ) as mock_ocr_factory:
            mock_isolator = MagicMock()
            mock_isolator.isolate_and_render.return_value = (
                simple_table_image,
                "local",
                None,
            )
            mock_isolator_cls.return_value = mock_isolator

            mock_ocr = MagicMock()
            mock_ocr.extract_tokens.return_value = OCRResult(
                tokens=[],
                engine_type="tesseract",
                mean_confidence=0.0,
                error="Tesseract not installed",
            )
            mock_ocr_factory.return_value = mock_ocr

            extractor = RenderFirstTableExtractor(save_debug_artifacts=False)
            extractor._converter = MagicMock()
            extractor._converter.is_available.return_value = True
            extractor._structure_recognizer = MagicMock()
            extractor._structure_recognizer.detect_cells.return_value = StructureResult(
                cells=sample_cells_3x3,
                num_rows=3,
                num_cols=3,
                recognizer_type="baseline_grid",
                confidence=0.9,
            )

            result = extractor.extract(mock_table, "/path/to/doc.docx", 0)

            assert result.is_usable is False
            assert result.failure_reason_code == "RENDER_FIRST_OCR_FAILED"


# =============================================================================
# Test: QualityMetrics Dataclass
# =============================================================================
class TestQualityMetrics:
    """Tests for QualityMetrics dataclass."""

    def test_to_dict_includes_all_fields(self):
        """Test QualityMetrics serialization."""
        metrics = QualityMetrics(
            token_coverage_ratio=0.85,
            empty_cell_ratio=0.15,
            mean_cell_confidence=0.88,
            p10_cell_confidence=0.72,
            total_tokens=50,
            assigned_tokens=45,
            numeric_cells=10,
        )
        d = metrics.to_dict()
        assert d["token_coverage_ratio"] == 0.85
        assert d["assigned_tokens"] == 45
        assert d["numeric_cells"] == 10
        assert "sanity_issues" in d


# =============================================================================
# Test: RenderFirstExtractionResult Dataclass
# =============================================================================
class TestRenderFirstExtractionResult:
    """Tests for RenderFirstExtractionResult dataclass."""

    def test_to_extraction_result_dict(self):
        """Test result serialization for API compatibility."""
        result = RenderFirstExtractionResult(
            grid=[["A", "B"], ["C", "D"]],
            quality_score=0.85,
            quality_flags=["BORDERLINE_CONFIDENCE"],
            is_usable=True,
            rows=2,
            cols=2,
        )
        d = result.to_extraction_result_dict()
        assert d["grid"] == [["A", "B"], ["C", "D"]]
        assert d["quality_score"] == 0.85
        assert "BORDERLINE_CONFIDENCE" in d["quality_flags"]
        assert d["is_usable"] is True

    def test_telemetry_fields_populated(self):
        """Test that telemetry fields can be populated."""
        result = RenderFirstExtractionResult(
            grid=[["A"]],
            conversion_mode="local",
            structure_recognizer="table_transformer",
            ocr_engine="tesseract",
            token_coverage_ratio=0.92,
            mean_cell_confidence=0.88,
            p10_cell_confidence=0.75,
            empty_cell_ratio=0.1,
        )
        assert result.conversion_mode == "local"
        assert result.structure_recognizer == "table_transformer"
        assert result.ocr_engine == "tesseract"
        assert result.token_coverage_ratio == 0.92
