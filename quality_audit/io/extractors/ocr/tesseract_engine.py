"""
Tesseract OCR engine implementation.
Uses pytesseract for text extraction with bounding boxes and confidence scores.
"""

import logging
from typing import List, Optional

import numpy as np

from .base import OCREngine, OCRResult, OCRToken

try:
    import pytesseract
    from pytesseract import Output

    HAS_TESSERACT = True
except ImportError:
    HAS_TESSERACT = False

try:
    from PIL import Image

    HAS_PIL = True
except ImportError:
    HAS_PIL = False


logger = logging.getLogger(__name__)


class TesseractOCREngine(OCREngine):
    """
    OCR engine using Tesseract via pytesseract.

    Provides per-word tokens with bounding boxes and confidence scores.
    """

    def __init__(
        self,
        lang: str = "eng+vie",
        config: Optional[str] = None,
        psm: int = 6,
    ):
        """
        Initialize Tesseract OCR engine.

        Args:
            lang: Tesseract language codes (default: English + Vietnamese).
            config: Additional Tesseract configuration.
            psm: Page segmentation mode.
                 6 = Assume a single uniform block of text (default).
                 3 = Fully automatic page segmentation.
                 11 = Sparse text.
        """
        self.lang = lang
        self.psm = psm
        self.config = config or f"--psm {psm}"
        self._available: Optional[bool] = None

    @property
    def engine_type(self) -> str:
        return "tesseract"

    def is_available(self) -> bool:
        """Check if Tesseract is installed and accessible."""
        if self._available is not None:
            return self._available

        if not HAS_TESSERACT:
            self._available = False
            return False

        try:
            pytesseract.get_tesseract_version()
            self._available = True
        except Exception:
            self._available = False

        return self._available

    def extract_tokens(self, image: np.ndarray) -> OCRResult:
        """
        Extract text tokens from image using Tesseract.

        Args:
            image: RGB numpy array of the image.

        Returns:
            OCRResult with tokens and metadata.
        """
        if not HAS_TESSERACT:
            return OCRResult(
                engine_type=self.engine_type,
                error="pytesseract not installed",
            )

        if not HAS_PIL:
            return OCRResult(
                engine_type=self.engine_type,
                error="PIL not installed",
            )

        if not self.is_available():
            return OCRResult(
                engine_type=self.engine_type,
                error="Tesseract not available",
            )

        if image is None or image.size == 0:
            return OCRResult(
                engine_type=self.engine_type,
                error="Empty image",
            )

        try:
            # Convert numpy array to PIL Image
            pil_image = Image.fromarray(image)

            # Run OCR with detailed output
            data = pytesseract.image_to_data(
                pil_image,
                lang=self.lang,
                config=self.config,
                output_type=Output.DICT,
            )

            tokens = self._parse_tesseract_output(data)

            return OCRResult(
                tokens=tokens,
                engine_type=self.engine_type,
            )

        except Exception as e:
            logger.warning("Tesseract OCR failed: %s", e)
            return OCRResult(
                engine_type=self.engine_type,
                error=str(e),
            )

    def _parse_tesseract_output(self, data: dict) -> List[OCRToken]:
        """Parse Tesseract output dictionary into tokens."""
        tokens = []

        n_boxes = len(data.get("text", []))

        for i in range(n_boxes):
            text = data["text"][i]

            # Skip empty text
            if not text or not text.strip():
                continue

            # Get bounding box
            x = data["left"][i]
            y = data["top"][i]
            w = data["width"][i]
            h = data["height"][i]

            # Get confidence (Tesseract returns -1 for some elements)
            conf = data["conf"][i]
            if conf == -1:
                conf = 0
            confidence = max(0.0, min(1.0, conf / 100.0))

            token = OCRToken(
                text=text.strip(),
                x1=x,
                y1=y,
                x2=x + w,
                y2=y + h,
                confidence=confidence,
            )
            tokens.append(token)

        return tokens


class EasyOCREngine(OCREngine):
    """
    OCR engine using EasyOCR.

    Provides better accuracy for multi-language documents but requires
    more resources and model download.
    """

    def __init__(self, languages: Optional[List[str]] = None, gpu: bool = False):
        """
        Initialize EasyOCR engine.

        Args:
            languages: List of language codes (default: ['en', 'vi']).
            gpu: Whether to use GPU acceleration.
        """
        self.languages = languages or ["en", "vi"]
        self.gpu = gpu
        self._reader = None
        self._available: Optional[bool] = None

    @property
    def engine_type(self) -> str:
        return "easyocr"

    def is_available(self) -> bool:
        """Check if EasyOCR is installed."""
        if self._available is not None:
            return self._available

        import importlib.util

        self._available = importlib.util.find_spec("easyocr") is not None

        return self._available

    def _get_reader(self):
        """Lazy initialization of EasyOCR reader."""
        if self._reader is None:
            import easyocr

            self._reader = easyocr.Reader(self.languages, gpu=self.gpu)
        return self._reader

    def extract_tokens(self, image: np.ndarray) -> OCRResult:
        """
        Extract text tokens from image using EasyOCR.

        Args:
            image: RGB numpy array of the image.

        Returns:
            OCRResult with tokens and metadata.
        """
        if not self.is_available():
            return OCRResult(
                engine_type=self.engine_type,
                error="EasyOCR not installed",
            )

        if image is None or image.size == 0:
            return OCRResult(
                engine_type=self.engine_type,
                error="Empty image",
            )

        try:
            reader = self._get_reader()

            # EasyOCR expects BGR or grayscale, but can handle RGB
            results = reader.readtext(image)

            tokens = self._parse_easyocr_output(results)

            return OCRResult(
                tokens=tokens,
                engine_type=self.engine_type,
            )

        except Exception as e:
            logger.warning("EasyOCR failed: %s", e)
            return OCRResult(
                engine_type=self.engine_type,
                error=str(e),
            )

    def _parse_easyocr_output(self, results: list) -> List[OCRToken]:
        """Parse EasyOCR output into tokens."""
        tokens = []

        for result in results:
            bbox, text, confidence = result

            if not text or not text.strip():
                continue

            # EasyOCR returns bbox as [[x1,y1], [x2,y1], [x2,y2], [x1,y2]]
            x_coords = [p[0] for p in bbox]
            y_coords = [p[1] for p in bbox]

            token = OCRToken(
                text=text.strip(),
                x1=int(min(x_coords)),
                y1=int(min(y_coords)),
                x2=int(max(x_coords)),
                y2=int(max(y_coords)),
                confidence=float(confidence),
            )
            tokens.append(token)

        return tokens


def get_best_ocr_engine(prefer_easyocr: bool = False) -> OCREngine:
    """
    Get the best available OCR engine.

    Args:
        prefer_easyocr: If True, prefer EasyOCR over Tesseract.

    Returns:
        The best available OCREngine instance.
    """
    tesseract = TesseractOCREngine()
    easyocr = EasyOCREngine()

    if prefer_easyocr and easyocr.is_available():
        return easyocr

    if tesseract.is_available():
        return tesseract

    if easyocr.is_available():
        return easyocr

    # Return Tesseract even if not available (will error cleanly)
    return tesseract
