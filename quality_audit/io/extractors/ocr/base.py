"""
OCR module for extracting text tokens from table images.
Provides abstract base class and implementations using Tesseract or EasyOCR.
"""

from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from typing import List, Optional

import numpy as np


@dataclass
class OCRToken:
    """Single OCR token with bounding box and confidence."""

    text: str
    x1: int  # left
    y1: int  # top
    x2: int  # right
    y2: int  # bottom
    confidence: float  # 0.0-1.0

    @property
    def width(self) -> int:
        return self.x2 - self.x1

    @property
    def height(self) -> int:
        return self.y2 - self.y1

    @property
    def center(self) -> tuple:
        return ((self.x1 + self.x2) // 2, (self.y1 + self.y2) // 2)

    @property
    def area(self) -> int:
        return self.width * self.height


@dataclass
class OCRResult:
    """Result of OCR extraction."""

    tokens: List[OCRToken] = field(default_factory=list)
    engine_type: str = "unknown"
    mean_confidence: float = 0.0
    error: Optional[str] = None

    def __post_init__(self):
        if self.tokens and self.mean_confidence == 0.0:
            confidences = [t.confidence for t in self.tokens if t.confidence > 0]
            if confidences:
                self.mean_confidence = sum(confidences) / len(confidences)

    @property
    def is_valid(self) -> bool:
        return len(self.tokens) > 0 and self.error is None


class OCREngine(ABC):
    """Abstract base class for OCR engines."""

    @abstractmethod
    def extract_tokens(self, image: np.ndarray) -> OCRResult:
        """
        Extract text tokens from an image.

        Args:
            image: RGB numpy array of the image.

        Returns:
            OCRResult with tokens and metadata.
        """
        pass

    @property
    @abstractmethod
    def engine_type(self) -> str:
        """Return identifier for this OCR engine."""
        pass

    def is_available(self) -> bool:
        """
        Whether this OCR engine can be used in the current environment.

        Implementations may override this (e.g., missing native deps).
        """
        return True
