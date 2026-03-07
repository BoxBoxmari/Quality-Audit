"""
Table Transformer structure recognizer using pretrained DETR-based model.

Phase 9: Advanced table structure recognition for merged/complex cells.
Uses microsoft/table-transformer-structure-recognition model from HuggingFace.
Falls back to BaselineGridRecognizer if model unavailable.
"""

import logging
from typing import List, Optional

import numpy as np

from .base import CellBox, StructureResult, TableStructureRecognizer

logger = logging.getLogger(__name__)

# Model availability flag
_TABLE_TRANSFORMER_AVAILABLE: Optional[bool] = None
_TABLE_TRANSFORMER_MODEL = None
_TABLE_TRANSFORMER_PROCESSOR = None


def _check_table_transformer_available() -> bool:
    """Check if table-transformer dependencies are available."""
    global _TABLE_TRANSFORMER_AVAILABLE
    if _TABLE_TRANSFORMER_AVAILABLE is not None:
        return _TABLE_TRANSFORMER_AVAILABLE

    try:
        import torch  # noqa: F401
        from transformers import (  # noqa: F401
            AutoModelForObjectDetection,
            TableTransformerForObjectDetection,
        )

        _TABLE_TRANSFORMER_AVAILABLE = True
    except ImportError as e:
        logger.debug("Table Transformer not available: %s", e)
        _TABLE_TRANSFORMER_AVAILABLE = False

    return _TABLE_TRANSFORMER_AVAILABLE


def _load_model():
    """Lazy-load the table transformer model."""
    global \
        _TABLE_TRANSFORMER_AVAILABLE, \
        _TABLE_TRANSFORMER_MODEL, \
        _TABLE_TRANSFORMER_PROCESSOR

    if _TABLE_TRANSFORMER_MODEL is not None:
        return _TABLE_TRANSFORMER_MODEL, _TABLE_TRANSFORMER_PROCESSOR

    if not _check_table_transformer_available():
        return None, None

    try:
        import torch
        from transformers import (
            AutoImageProcessor,
            TableTransformerForObjectDetection,
        )

        model_name = "microsoft/table-transformer-structure-recognition"
        logger.info("Loading Table Transformer model: %s", model_name)

        _TABLE_TRANSFORMER_PROCESSOR = AutoImageProcessor.from_pretrained(model_name)
        _TABLE_TRANSFORMER_MODEL = TableTransformerForObjectDetection.from_pretrained(
            model_name
        )

        # Move to GPU if available
        device = "cuda" if torch.cuda.is_available() else "cpu"
        _TABLE_TRANSFORMER_MODEL.to(device)
        _TABLE_TRANSFORMER_MODEL.eval()

        logger.info("Table Transformer model loaded on %s", device)
        return _TABLE_TRANSFORMER_MODEL, _TABLE_TRANSFORMER_PROCESSOR

    except Exception as e:
        logger.warning("Failed to load Table Transformer model: %s", e)
        _TABLE_TRANSFORMER_AVAILABLE = False
        return None, None


class TableTransformerRecognizer(TableStructureRecognizer):
    """
    Table structure recognizer using Microsoft's Table Transformer (DETR-based).

    This model provides superior accuracy for complex tables with merged cells,
    spanning cells, and irregular layouts compared to heuristic-based methods.

    Requires:
        - torch
        - transformers
        - GPU recommended for performance (falls back to CPU)

    If dependencies are missing, is_available() returns False and the
    BaselineGridRecognizer should be used as fallback.
    """

    # Class mapping from Table Transformer output
    LABEL_MAP = {
        0: "table",
        1: "table column",
        2: "table row",
        3: "table column header",
        4: "table projected row header",
        5: "table spanning cell",
    }

    def __init__(self, confidence_threshold: float = 0.5):
        """
        Initialize Table Transformer recognizer.

        Args:
            confidence_threshold: Minimum confidence for detected elements.
        """
        self.confidence_threshold = confidence_threshold
        self._model = None
        self._processor = None

    @staticmethod
    def is_available() -> bool:
        """Check if Table Transformer is available."""
        return _check_table_transformer_available()

    def _ensure_model_loaded(self) -> bool:
        """Load model if not already loaded."""
        if self._model is None:
            self._model, self._processor = _load_model()
        return self._model is not None

    def detect_cells(self, image: np.ndarray) -> StructureResult:
        """
        Detect table cells using Table Transformer model.

        Args:
            image: RGB numpy array of the table image.

        Returns:
            StructureResult with detected cells and metadata.
        """
        if not self._ensure_model_loaded():
            return StructureResult(
                cells=[],
                num_rows=0,
                num_cols=0,
                recognizer_type=self.recognizer_type,
                confidence=0.0,
                error="Table Transformer model not available",
            )

        try:
            import torch
            from PIL import Image

            processor = self._processor
            model = self._model
            assert processor is not None and model is not None

            # Convert numpy array to PIL Image
            pil_image = Image.fromarray(image)
            img_width, img_height = pil_image.size

            # Process image
            inputs = processor(images=pil_image, return_tensors="pt")
            device = next(model.parameters()).device
            inputs = {k: v.to(device) for k, v in inputs.items()}

            # Run inference
            with torch.no_grad():
                outputs = model(**inputs)

            # Post-process outputs
            target_sizes = torch.tensor([[img_height, img_width]])
            results = processor.post_process_object_detection(
                outputs, threshold=self.confidence_threshold, target_sizes=target_sizes
            )[0]

            # Extract rows and columns from detections
            rows: List[dict] = []
            cols: List[dict] = []
            spanning_cells: List[dict] = []

            for score, label, box in zip(
                results["scores"], results["labels"], results["boxes"]
            ):
                label_int = label.item()
                conf = score.item()
                x1, y1, x2, y2 = box.tolist()

                label_name = self.LABEL_MAP.get(label_int, "unknown")

                if label_name == "table row":
                    rows.append(
                        {"y1": y1, "y2": y2, "x1": x1, "x2": x2, "confidence": conf}
                    )
                elif label_name == "table column":
                    cols.append(
                        {"x1": x1, "x2": x2, "y1": y1, "y2": y2, "confidence": conf}
                    )
                elif label_name == "table spanning cell":
                    spanning_cells.append(
                        {
                            "x1": x1,
                            "y1": y1,
                            "x2": x2,
                            "y2": y2,
                            "confidence": conf,
                        }
                    )

            # Sort rows by y-coordinate, columns by x-coordinate
            rows.sort(key=lambda r: r["y1"])
            cols.sort(key=lambda c: c["x1"])

            if not rows or not cols:
                return StructureResult(
                    cells=[],
                    num_rows=0,
                    num_cols=0,
                    recognizer_type=self.recognizer_type,
                    confidence=0.0,
                    error="No rows or columns detected",
                )

            # Build cell grid from row/column intersections
            cells = self._build_cells_from_grid(
                rows, cols, spanning_cells, img_width, img_height
            )

            avg_confidence = (
                sum(c.confidence for c in cells) / len(cells) if cells else 0.0
            )

            return StructureResult(
                cells=cells,
                num_rows=len(rows),
                num_cols=len(cols),
                recognizer_type=self.recognizer_type,
                confidence=avg_confidence,
                error=None,
            )

        except Exception as e:
            logger.exception("Table Transformer detection failed: %s", e)
            return StructureResult(
                cells=[],
                num_rows=0,
                num_cols=0,
                recognizer_type=self.recognizer_type,
                confidence=0.0,
                error=str(e),
            )

    def _build_cells_from_grid(
        self,
        rows: List[dict],
        cols: List[dict],
        spanning_cells: List[dict],
        img_width: int,
        img_height: int,
    ) -> List[CellBox]:
        """
        Build cell boxes from detected rows, columns, and spanning cells.

        Args:
            rows: List of row detection dicts with y1, y2, confidence
            cols: List of column detection dicts with x1, x2, confidence
            spanning_cells: List of spanning cell detections
            img_width: Image width for bounds checking
            img_height: Image height for bounds checking

        Returns:
            List of CellBox objects.
        """
        cells: List[CellBox] = []

        # Create mask for cells covered by spanning cells
        covered_cells: set = set()

        # Process spanning cells first
        for span in spanning_cells:
            # Find which rows/cols this spanning cell covers
            span_rows = [
                i
                for i, r in enumerate(rows)
                if self._overlaps(span["y1"], span["y2"], r["y1"], r["y2"])
            ]
            span_cols = [
                i
                for i, c in enumerate(cols)
                if self._overlaps(span["x1"], span["x2"], c["x1"], c["x2"])
            ]

            if span_rows and span_cols:
                min_row, max_row = min(span_rows), max(span_rows)
                min_col, max_col = min(span_cols), max(span_cols)

                # Mark cells as covered
                for r in range(min_row, max_row + 1):
                    for c in range(min_col, max_col + 1):
                        covered_cells.add((r, c))

                # Add spanning cell
                cells.append(
                    CellBox(
                        row=min_row,
                        col=min_col,
                        x1=int(span["x1"]),
                        y1=int(span["y1"]),
                        x2=int(span["x2"]),
                        y2=int(span["y2"]),
                        row_span=max_row - min_row + 1,
                        col_span=max_col - min_col + 1,
                        confidence=span["confidence"],
                    )
                )

        # Create regular cells for non-covered intersections
        for row_idx, row in enumerate(rows):
            for col_idx, col in enumerate(cols):
                if (row_idx, col_idx) in covered_cells:
                    continue

                cell = CellBox(
                    row=row_idx,
                    col=col_idx,
                    x1=int(max(0, col["x1"])),
                    y1=int(max(0, row["y1"])),
                    x2=int(min(img_width, col["x2"])),
                    y2=int(min(img_height, row["y2"])),
                    row_span=1,
                    col_span=1,
                    confidence=min(row["confidence"], col["confidence"]),
                )
                cells.append(cell)

        # Sort by row, then column
        cells.sort(key=lambda c: (c.row, c.col))

        return cells

    @staticmethod
    def _overlaps(a1: float, a2: float, b1: float, b2: float) -> bool:
        """Check if two 1D ranges overlap significantly (>50%)."""
        overlap = max(0, min(a2, b2) - max(a1, b1))
        len_a = a2 - a1
        len_b = b2 - b1
        if len_a <= 0 or len_b <= 0:
            return False
        return overlap / min(len_a, len_b) > 0.5

    @property
    def recognizer_type(self) -> str:
        """Return identifier for this recognizer type."""
        return "table_transformer"
