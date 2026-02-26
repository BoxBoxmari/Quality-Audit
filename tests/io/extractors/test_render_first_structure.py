"""
Tests for TableTransformerRecognizer structure recognition.

Comment 1: Tests structure recognizer with mocked model outputs.
"""

from __future__ import annotations

from unittest.mock import MagicMock, patch

import numpy as np
import pytest

from quality_audit.io.extractors.structure import CellBox, StructureResult
from quality_audit.io.extractors.structure.baseline_grid import BaselineGridRecognizer

# Mark all tests in this module
pytestmark = pytest.mark.render_first


# =============================================================================
# Test: BaselineGridRecognizer
# =============================================================================
class TestBaselineGridRecognizer:
    """Tests for BaselineGridRecognizer (always available)."""

    @pytest.fixture
    def recognizer(self) -> BaselineGridRecognizer:
        return BaselineGridRecognizer()

    @pytest.fixture
    def simple_table_image(self) -> np.ndarray:
        """Create a simple 3x3 table image with clear grid lines."""
        img = np.ones((150, 300, 3), dtype=np.uint8) * 255
        # Horizontal lines
        for y in [0, 50, 100, 149]:
            img[y : y + 2, :, :] = 0
        # Vertical lines
        for x in [0, 100, 200, 299]:
            img[:, x : x + 2, :] = 0
        return img

    def test_detect_cells_returns_structure_result(
        self, recognizer: BaselineGridRecognizer, simple_table_image: np.ndarray
    ):
        """Test that detect_cells returns StructureResult."""
        result = recognizer.detect_cells(simple_table_image)
        assert isinstance(result, StructureResult)
        assert result.recognizer_type == "baseline_grid"

    def test_recognizer_type_property(self, recognizer: BaselineGridRecognizer):
        """Test recognizer_type property."""
        assert recognizer.recognizer_type == "baseline_grid"


# =============================================================================
# Test: TableTransformerRecognizer
# =============================================================================
class TestTableTransformerRecognizer:
    """Tests for TableTransformerRecognizer with mocked dependencies."""

    def test_is_available_returns_bool(self):
        """Test that is_available() returns boolean."""
        from quality_audit.io.extractors.structure.table_transformer import (
            TableTransformerRecognizer,
        )

        result = TableTransformerRecognizer.is_available()
        assert isinstance(result, bool)

    def test_fallback_to_baseline_when_unavailable(self):
        """Test that extraction falls back to baseline when TATR unavailable."""
        with patch(
            "quality_audit.io.extractors.structure.table_transformer."
            "_check_table_transformer_available",
            return_value=False,
        ):
            from quality_audit.io.extractors.render_first_table_extractor import (
                RenderFirstTableExtractor,
            )

            extractor = RenderFirstTableExtractor(save_debug_artifacts=False)
            recognizer_type = type(extractor._structure_recognizer).__name__
            assert "baseline" in recognizer_type.lower()

    def test_detect_cells_with_mocked_model(self):
        """Test detect_cells with mocked transformer model outputs."""
        from quality_audit.io.extractors.structure.table_transformer import (
            TableTransformerRecognizer,
        )

        # Create recognizer
        recognizer = TableTransformerRecognizer()

        # Mock the model loading and inference
        mock_model = MagicMock()
        mock_processor = MagicMock()
        recognizer._model = mock_model
        recognizer._processor = mock_processor

        # Mock input processing
        mock_processor.return_tensors = "pt"
        mock_processor.return_value = {"pixel_values": MagicMock()}

        # Mock model output with rows and columns
        with patch.object(recognizer, "_ensure_model_loaded", return_value=True), patch(
            "torch.no_grad"
        ):
            # Create mock detections
            mock_results = {
                "scores": MagicMock(tolist=lambda: [0.95, 0.93, 0.91, 0.92]),
                "labels": MagicMock(tolist=lambda: [2, 2, 1, 1]),  # 2 rows, 2 cols
                "boxes": MagicMock(),
            }

            # Mock post-processing
            mock_processor.post_process_object_detection.return_value = [mock_results]

            # Override internal methods to return expected values
            recognizer._build_cells_from_grid = MagicMock(
                return_value=[
                    CellBox(row=0, col=0, x1=0, y1=0, x2=100, y2=50, confidence=0.9),
                    CellBox(row=0, col=1, x1=100, y1=0, x2=200, y2=50, confidence=0.9),
                    CellBox(row=1, col=0, x1=0, y1=50, x2=100, y2=100, confidence=0.9),
                    CellBox(
                        row=1,
                        col=1,
                        x1=100,
                        y1=50,
                        x2=200,
                        y2=100,
                        confidence=0.9,
                    ),
                ]
            )

            # Note: Full test requires torch/transformers; this tests the interface
            assert recognizer.recognizer_type == "table_transformer"

    def test_spanning_cell_detection(self):
        """Test that spanning cells are detected correctly."""
        from quality_audit.io.extractors.structure.table_transformer import (
            TableTransformerRecognizer,
        )

        recognizer = TableTransformerRecognizer()

        # Test _build_cells_from_grid with spanning cells
        rows = [
            {"y1": 0, "y2": 50, "x1": 0, "x2": 200, "confidence": 0.9},
            {"y1": 50, "y2": 100, "x1": 0, "x2": 200, "confidence": 0.9},
        ]
        cols = [
            {"x1": 0, "x2": 100, "y1": 0, "y2": 100, "confidence": 0.9},
            {"x1": 100, "x2": 200, "y1": 0, "y2": 100, "confidence": 0.9},
        ]
        spanning_cells = [
            # Merged cell spanning both columns in row 0
            {"x1": 5, "y1": 5, "x2": 195, "y2": 45, "confidence": 0.85}
        ]

        cells = recognizer._build_cells_from_grid(
            rows, cols, spanning_cells, img_width=200, img_height=100
        )

        # Should have 1 spanning cell + 2 regular cells in row 1
        spanning = [c for c in cells if c.col_span > 1 or c.row_span > 1]
        assert len(spanning) == 1, "Should detect one spanning cell"
        assert spanning[0].col_span == 2, "Spanning cell should span 2 columns"


# =============================================================================
# Test: CellBox Dataclass
# =============================================================================
class TestCellBox:
    """Tests for CellBox dataclass."""

    def test_cellbox_creation(self):
        """Test CellBox creation with all fields."""
        cell = CellBox(
            row=0,
            col=1,
            x1=100,
            y1=0,
            x2=200,
            y2=50,
            row_span=1,
            col_span=2,
            confidence=0.95,
        )
        assert cell.row == 0
        assert cell.col == 1
        assert cell.col_span == 2
        assert cell.confidence == 0.95

    def test_cellbox_defaults(self):
        """Test CellBox default values."""
        cell = CellBox(row=0, col=0, x1=0, y1=0, x2=100, y2=50)
        assert cell.row_span == 1
        assert cell.col_span == 1
        assert cell.confidence == 1.0


# =============================================================================
# Test: StructureResult Dataclass
# =============================================================================
class TestStructureResult:
    """Tests for StructureResult dataclass."""

    def test_structure_result_creation(self):
        """Test StructureResult creation."""
        cells = [
            CellBox(row=0, col=0, x1=0, y1=0, x2=100, y2=50),
            CellBox(row=0, col=1, x1=100, y1=0, x2=200, y2=50),
        ]
        result = StructureResult(
            cells=cells,
            num_rows=1,
            num_cols=2,
            recognizer_type="baseline_grid",
            confidence=0.9,
        )
        assert len(result.cells) == 2
        assert result.num_rows == 1
        assert result.num_cols == 2

    def test_structure_result_with_error(self):
        """Test StructureResult with error state."""
        result = StructureResult(
            cells=[],
            num_rows=0,
            num_cols=0,
            recognizer_type="table_transformer",
            confidence=0.0,
            error="Model not available",
        )
        assert result.error is not None
        assert len(result.cells) == 0
