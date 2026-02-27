"""
DOCX to PDF conversion using local LibreOffice (soffice).
"""

import logging
import os
import shutil
import subprocess
import tempfile
from pathlib import Path
from typing import Optional, Tuple

logger = logging.getLogger(__name__)


class LocalSofficeConverter:
    """Local LibreOffice (soffice) converter."""

    TIMEOUT_SECONDS = 60

    def __init__(self) -> None:
        self._soffice_path: Optional[str] = None
        self._available: Optional[bool] = None

    def _find_soffice(self) -> Optional[str]:
        """Locate soffice executable."""
        if self._soffice_path is not None:
            return self._soffice_path

        names = ["soffice", "soffice.exe"]
        for name in names:
            path = shutil.which(name)
            if path:
                self._soffice_path = path
                return path

        # Check common Windows paths
        if os.name == "nt":
            for base in (
                os.path.expandvars(r"%ProgramFiles%\LibreOffice\program"),
                os.path.expandvars(r"%ProgramFiles(x86)%\LibreOffice\program"),
            ):
                for name in names:
                    p = os.path.join(base, name)
                    if os.path.isfile(p):
                        self._soffice_path = p
                        return p

        return None

    def is_available(self) -> bool:
        """Check if soffice is available locally."""
        if self._available is not None:
            return self._available
        self._available = self._find_soffice() is not None
        return self._available

    def convert_docx_to_pdf(
        self, docx_path: Path, output_pdf_path: Path
    ) -> Tuple[bool, str]:
        """
        Convert DOCX to PDF using local soffice.

        Args:
            docx_path: Path to input DOCX file.
            output_pdf_path: Path where PDF should be written.

        Returns:
            Tuple of (success, error_message).
        """
        soffice = self._find_soffice()
        if not soffice:
            return False, "soffice not found"

        docx_path = Path(docx_path).resolve()
        output_pdf_path = Path(output_pdf_path).resolve()

        if not docx_path.exists():
            return False, f"Input file not found: {docx_path}"

        with tempfile.TemporaryDirectory() as temp_dir:
            temp_dir_path = Path(temp_dir)

            cmd = [
                soffice,
                "--headless",
                "--convert-to",
                "pdf",
                "--outdir",
                str(temp_dir_path),
                str(docx_path),
            ]

            try:
                result = subprocess.run(
                    cmd,
                    capture_output=True,
                    text=True,
                    timeout=self.TIMEOUT_SECONDS,
                    cwd=str(temp_dir_path),
                )

                if result.returncode != 0:
                    return False, f"soffice conversion failed: {result.stderr}"

                # Find generated PDF
                pdf_name = docx_path.stem + ".pdf"
                generated_pdf = temp_dir_path / pdf_name

                if not generated_pdf.exists():
                    return False, "PDF not generated"

                # Ensure output directory exists
                output_pdf_path.parent.mkdir(parents=True, exist_ok=True)
                shutil.move(str(generated_pdf), str(output_pdf_path))
                return True, ""

            except subprocess.TimeoutExpired:
                return False, "soffice conversion timed out"
            except Exception as e:
                return False, f"soffice conversion error: {e}"


class WordComConverter:
    """DOCX to PDF conversion using Microsoft Word via PowerShell COM."""

    TIMEOUT_SECONDS = 120

    def __init__(self) -> None:
        self._available: Optional[bool] = None
        self._powershell_path: Optional[str] = None

    def _find_powershell(self) -> Optional[str]:
        """Locate PowerShell executable on Windows."""
        if self._powershell_path is not None:
            return self._powershell_path
        if os.name != "nt":
            return None
        for name in ("powershell.exe", "powershell"):
            path = shutil.which(name)
            if path:
                self._powershell_path = path
                return path
        return None

    def is_available(self) -> bool:
        """Check if Word COM conversion is available on this machine."""
        if self._available is not None:
            return self._available
        self._available = self._find_powershell() is not None
        return self._available

    def _escape_path_for_powershell(self, path: Path) -> str:
        """
        Escape path for inclusion in a single-quoted PowerShell string.
        """
        return str(path).replace("'", "''")

    def convert_docx_to_pdf(
        self, docx_path: Path, output_pdf_path: Path
    ) -> Tuple[bool, str]:
        """
        Convert DOCX to PDF using Microsoft Word via PowerShell COM automation.

        Args:
            docx_path: Path to input DOCX file.
            output_pdf_path: Path where PDF should be written.

        Returns:
            Tuple of (success, error_message).
        """
        if not self.is_available():
            return False, "Word COM converter not available"

        docx_path = Path(docx_path).resolve()
        output_pdf_path = Path(output_pdf_path).resolve()

        if not docx_path.exists():
            return False, f"Input file not found: {docx_path}"

        # Ensure output directory exists before calling Word
        output_pdf_path.parent.mkdir(parents=True, exist_ok=True)

        ps_exe = self._find_powershell()
        if not ps_exe:
            return False, "powershell not found"

        docx_ps = self._escape_path_for_powershell(docx_path)
        pdf_ps = self._escape_path_for_powershell(output_pdf_path)

        # PowerShell script: open Word hidden, export as PDF, close.
        script = (
            "$ErrorActionPreference = 'Stop';"
            "$word = New-Object -ComObject Word.Application;"
            "$word.Visible = $false;"
            f"$doc = $word.Documents.Open('{docx_ps}');"
            f"$doc.ExportAsFixedFormat('{pdf_ps}', 17);"
            "$doc.Close();"
            "$word.Quit();"
        )

        try:
            logger.info(
                "WordComConverter: starting DOCX→PDF conversion "
                "(mode=word_com, docx=%s, pdf=%s)",
                docx_path,
                output_pdf_path,
            )
            result = subprocess.run(
                [
                    ps_exe,
                    "-NoProfile",
                    "-ExecutionPolicy",
                    "Bypass",
                    "-Command",
                    script,
                ],
                capture_output=True,
                text=True,
                timeout=self.TIMEOUT_SECONDS,
            )
        except subprocess.TimeoutExpired:
            logger.warning(
                "WordComConverter: PowerShell conversion timed out for %s", docx_path
            )
            return False, "Word COM conversion timed out"
        except Exception as e:
            logger.warning(
                "WordComConverter: PowerShell conversion error for %s: %s",
                docx_path,
                e,
            )
            return False, f"Word COM conversion error: {e}"

        if result.returncode != 0:
            logger.warning(
                "WordComConverter: PowerShell returned %s for %s: %s",
                result.returncode,
                docx_path,
                (result.stderr or "").strip(),
            )
            return False, f"Word COM conversion failed: {result.stderr}"

        if not output_pdf_path.exists():
            return False, "PDF not generated by Word COM"

        return True, ""


class FallbackConverter:
    """
    DOCX to PDF conversion using local converters (Word COM and/or soffice).
    """

    def __init__(self, docker_image: Optional[str] = None) -> None:
        del docker_image  # Unused; kept for backward-compatible signature
        self._word_com_converter = WordComConverter()
        self._local_converter = LocalSofficeConverter()

    def convert(self, docx_path: Path, output_pdf_path: Path) -> Tuple[bool, str, str]:
        """
        Convert DOCX to PDF using the best available backend.

        Args:
            docx_path: Path to input DOCX file.
            output_pdf_path: Path where PDF should be written.

        Returns:
            Tuple of (success, mode, error_message).
            mode is one of: "word_com", "local", "unavailable"
        """
        # Prefer Word COM on Windows when available
        if self._word_com_converter.is_available():
            success, error = self._word_com_converter.convert_docx_to_pdf(
                docx_path, output_pdf_path
            )
            if success:
                return True, "word_com", ""
            if error:
                logger.warning(
                    "FallbackConverter: WordComConverter failed for %s: %s",
                    docx_path,
                    error,
                )

        # Fallback to local soffice if available
        if self._local_converter.is_available():
            success, error = self._local_converter.convert_docx_to_pdf(
                docx_path, output_pdf_path
            )
            if success:
                return True, "local", ""
            return False, "local", error

        return False, "unavailable", "no converter available"

    def is_available(self) -> bool:
        """Check if any conversion backend is available."""
        return (
            self._word_com_converter.is_available()
            or self._local_converter.is_available()
        )

    def get_available_mode(self) -> str:
        """Get the mode that would be used for conversion."""
        if self._word_com_converter.is_available():
            return "word_com"
        if self._local_converter.is_available():
            return "local"
        return "unavailable"
