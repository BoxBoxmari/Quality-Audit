"""
Table isolation and PDF/image rendering utilities.
Isolates single tables to temporary DOCX and renders PDF pages as images.
"""

from __future__ import annotations

import logging
import tempfile
from pathlib import Path
from typing import TYPE_CHECKING, Optional, Tuple

if TYPE_CHECKING:
    from .conversion import FallbackConverter

import numpy as np

try:
    from docx import Document
    from docx.table import Table

    HAS_DOCX = True
except ImportError:
    HAS_DOCX = False

try:
    import fitz  # PyMuPDF

    HAS_PYMUPDF = True
except ImportError:
    HAS_PYMUPDF = False

try:
    from pdf2image import convert_from_path

    HAS_PDF2IMAGE = True
except ImportError:
    HAS_PDF2IMAGE = False


logger = logging.getLogger(__name__)


class TableIsolator:
    """
    Isolates a single table from a DOCX to a new DOCX file
    and renders PDF pages as images for OCR processing.
    """

    def __init__(self, dpi: int = 300):
        """
        Initialize the TableIsolator.

        Args:
            dpi: Resolution for PDF to image rendering. Default 300.
        """
        self.dpi = dpi

    def isolate_table_to_docx(
        self, table: Table, output_path: Path
    ) -> Tuple[bool, str]:
        """
        Create a minimal DOCX containing only the specified table.

        This approach copies the table XML element to a new document,
        which preserves basic structure (rows, cells, text, gridSpan, vMerge)
        but may lose external resources like images or hyperlinks.

        Args:
            table: python-docx Table object to isolate.
            output_path: Path where the new DOCX should be saved.

        Returns:
            Tuple of (success, error_message).
        """
        if not HAS_DOCX:
            return False, "python-docx not available"

        try:
            output_path = Path(output_path)
            output_path.parent.mkdir(parents=True, exist_ok=True)

            # Create a new blank document
            new_doc = Document()

            # Get the table XML element
            table_element = table._element

            # Copy the table element to the new document body
            # We use deepcopy to avoid modifying the original
            from copy import deepcopy

            new_table_element = deepcopy(table_element)
            new_doc.element.body.append(new_table_element)

            # Save the new document
            new_doc.save(str(output_path))

            return True, ""

        except Exception as e:
            logger.warning("Table isolation failed: %s", e)
            return False, str(e)

    def render_pdf_to_image(
        self,
        pdf_path: Path,
        page_num: int = 0,
        dpi: Optional[int] = None,
    ) -> Tuple[Optional[np.ndarray], str]:
        """
        Render a PDF page to an RGB numpy array.

        Args:
            pdf_path: Path to PDF file.
            page_num: Zero-indexed page number to render. Default 0.
            dpi: Resolution for rendering. Uses instance default if None.

        Returns:
            Tuple of (image_array, error_message).
            image_array is None on failure.
        """
        dpi = dpi or self.dpi
        pdf_path = Path(pdf_path)

        if not pdf_path.exists():
            return None, f"PDF file not found: {pdf_path}"

        # Try PyMuPDF first (faster, more reliable)
        if HAS_PYMUPDF:
            try:
                doc = fitz.open(str(pdf_path))
                if page_num >= len(doc):
                    doc.close()
                    return (
                        None,
                        f"Page {page_num} not found (document has {len(doc)} pages)",
                    )

                page = doc.load_page(page_num)
                # Compute zoom factor for desired DPI (PDF default is 72 DPI)
                zoom = dpi / 72.0
                mat = fitz.Matrix(zoom, zoom)
                pix = page.get_pixmap(matrix=mat, colorspace=fitz.csRGB)

                # Convert to numpy array
                img = np.frombuffer(pix.samples, dtype=np.uint8).reshape(
                    pix.height, pix.width, pix.n
                )

                # Ensure RGB (drop alpha if present)
                if img.shape[2] == 4:
                    img = img[:, :, :3]

                doc.close()
                return img, ""

            except Exception as e:
                logger.debug("PyMuPDF rendering failed: %s", e)

        # Fallback to pdf2image (uses poppler)
        if HAS_PDF2IMAGE:
            try:
                images = convert_from_path(
                    str(pdf_path),
                    dpi=dpi,
                    first_page=page_num + 1,  # 1-indexed
                    last_page=page_num + 1,
                )
                if images:
                    img = np.array(images[0])
                    return img, ""
                return None, "No image generated"

            except Exception as e:
                logger.debug("pdf2image rendering failed: %s", e)

        return None, "No PDF rendering library available (install PyMuPDF or pdf2image)"

    def isolate_and_render(
        self,
        table: Table,
        converter: FallbackConverter,
        work_dir: Optional[Path] = None,
    ) -> Tuple[Optional[np.ndarray], str, str]:
        """
        Full pipeline: isolate table → convert to PDF → render as image.

        Args:
            table: python-docx Table object.
            converter: FallbackConverter instance for DOCX→PDF conversion.
            work_dir: Optional working directory. Uses temp dir if None.

        Returns:
            Tuple of (image_array, conversion_mode, error_message).
            image_array is None on failure.
        """
        cleanup = False
        if work_dir is None:
            work_dir = Path(tempfile.mkdtemp(prefix="quality_audit_"))
            cleanup = True

        try:
            work_dir = Path(work_dir)
            work_dir.mkdir(parents=True, exist_ok=True)

            # Step 1: Isolate table to DOCX
            temp_docx = work_dir / "isolated_table.docx"
            success, error = self.isolate_table_to_docx(table, temp_docx)
            if not success:
                return None, "unavailable", f"Isolation failed: {error}"

            # Step 2: Convert DOCX to PDF
            temp_pdf = work_dir / "isolated_table.pdf"
            success, mode, error = converter.convert(temp_docx, temp_pdf)
            if not success:
                return None, mode, f"Conversion failed: {error}"

            # Step 3: Render PDF to image
            img, error = self.render_pdf_to_image(temp_pdf)
            if img is None:
                return None, mode, f"Rendering failed: {error}"

            return img, mode, ""

        finally:
            # Cleanup temp files if we created them
            if cleanup:
                import contextlib
                import shutil

                with contextlib.suppress(Exception):
                    shutil.rmtree(str(work_dir), ignore_errors=True)


def get_table_image(
    table: Table,
    converter: Optional[FallbackConverter] = None,
    dpi: int = 300,
) -> Tuple[Optional[np.ndarray], str, str]:
    """
    Convenience function to get an image of a table.

    Args:
        table: python-docx Table object.
        converter: FallbackConverter instance. Created if None.
        dpi: Resolution for rendering.

    Returns:
        Tuple of (image_array, conversion_mode, error_message).
    """
    if converter is None:
        from .conversion import FallbackConverter

        converter = FallbackConverter()

    isolator = TableIsolator(dpi=dpi)
    return isolator.isolate_and_render(table, converter)
