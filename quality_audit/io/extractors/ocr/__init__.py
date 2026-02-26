"""OCR module for text extraction from images."""

from .base import OCREngine, OCRResult, OCRToken
from .tesseract_engine import (
    EasyOCREngine,
    TesseractOCREngine,
    get_best_ocr_engine,
)

__all__ = [
    "OCREngine",
    "OCRResult",
    "OCRToken",
    "TesseractOCREngine",
    "EasyOCREngine",
    "get_best_ocr_engine",
]
