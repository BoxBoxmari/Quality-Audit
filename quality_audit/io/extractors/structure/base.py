"""
Table structure recognition module.
Provides abstract base class and implementations for detecting table cell structure in images.
"""

from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from typing import List, Optional, Tuple

import numpy as np


@dataclass
class CellBox:
    """Detected cell bounding box with grid position."""

    row: int
    col: int
    x1: int  # left
    y1: int  # top
    x2: int  # right
    y2: int  # bottom
    row_span: int = 1
    col_span: int = 1
    confidence: float = 1.0

    @property
    def width(self) -> int:
        return self.x2 - self.x1

    @property
    def height(self) -> int:
        return self.y2 - self.y1

    @property
    def center(self) -> Tuple[int, int]:
        return ((self.x1 + self.x2) // 2, (self.y1 + self.y2) // 2)

    @property
    def area(self) -> int:
        return self.width * self.height


@dataclass
class StructureResult:
    """Result of table structure recognition."""

    cells: List[CellBox] = field(default_factory=list)
    num_rows: int = 0
    num_cols: int = 0
    recognizer_type: str = "unknown"
    confidence: float = 0.0
    error: Optional[str] = None

    @property
    def is_valid(self) -> bool:
        return len(self.cells) > 0 and self.num_rows > 0 and self.num_cols > 0


class TableStructureRecognizer(ABC):
    """Abstract base class for table structure recognition."""

    @abstractmethod
    def detect_cells(self, image: np.ndarray) -> StructureResult:
        """
        Detect table cells in an image.

        Args:
            image: RGB numpy array of the table image.

        Returns:
            StructureResult with detected cells and metadata.
        """
        pass

    @property
    @abstractmethod
    def recognizer_type(self) -> str:
        """Return identifier for this recognizer type."""
        pass
