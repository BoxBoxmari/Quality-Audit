"""
Word document reading and table extraction utilities.
"""

import asyncio
from concurrent.futures import ThreadPoolExecutor
from typing import Any, Dict, List, Optional, Tuple

import docx
import pandas as pd


class WordReader:
    """Handles reading and parsing Word documents with financial tables."""

    def __init__(self):
        """Initialize Word reader."""
        pass

    def read_tables_with_headings(
        self, file_path: str
    ) -> List[Tuple[pd.DataFrame, Optional[str]]]:
        """
        Read tables from Word document and extract associated headings.

        Args:
            file_path: Path to Word document

        Returns:
            List[Tuple[pd.DataFrame, Optional[str]]]: List of (table_df, heading) pairs

        Raises:
            FileNotFoundError: If file doesn't exist
            docx.opc.exceptions.PackageNotFoundError: If file is corrupted
        """
        doc = docx.Document(file_path)
        tables = []
        headings = []
        current_heading = None
        sec = 0
        current_section = doc.sections[sec] if doc.sections else None

        for block in doc.element.body:
            if block.tag.endswith("tbl"):
                # Try to extract heading from section header if no current heading
                if current_heading is None or current_heading in [
                    "balance sheet",
                    "statement of income",
                ]:
                    if current_section:
                        for para in current_section.header.paragraphs:
                            text = para.text.strip().lower()
                            if "balance sheet" in text:
                                current_heading = "balance sheet"
                                break
                            elif "statement of income" in text:
                                current_heading = "statement of income"
                                break
                            elif "statement of cash flows" in text:
                                current_heading = "statement of cash flows"
                                break

                # Parse table
                table = docx.table.Table(block, doc)
                rows = [[cell.text.strip() for cell in row.cells] for row in table.rows]
                df = pd.DataFrame(rows)

                tables.append(df)
                headings.append(current_heading)

            elif block.tag.endswith("p"):
                paragraph = docx.text.paragraph.Paragraph(block, doc)

                # Handle section breaks
                sectPr = block.xpath(".//w:sectPr")
                if sectPr:
                    sec = sec + 1
                    if sec < len(doc.sections):
                        current_section = doc.sections[sec]

                # Extract heading if it's a heading paragraph
                if paragraph.style.name.startswith("Heading"):
                    current_heading = paragraph.text.strip()

        return list(zip(tables, headings))

    def extract_heading_from_section(self, section) -> Optional[str]:
        """
        Extract financial statement type from section header.

        Args:
            section: Document section

        Returns:
            Optional[str]: Detected heading type or None
        """
        if not section or not hasattr(section, "header"):
            return None

        for para in section.header.paragraphs:
            text = para.text.strip().lower()
            if "balance sheet" in text:
                return "balance sheet"
            elif "statement of income" in text:
                return "statement of income"
            elif "statement of cash flows" in text:
                return "statement of cash flows"

        return None

    def validate_document_structure(self, file_path: str) -> Dict[str, Any]:
        """
        Validate Word document structure and content.

        Args:
            file_path: Path to Word document

        Returns:
            Dict with validation results
        """
        try:
            doc = docx.Document(file_path)

            # Count tables and paragraphs
            table_count = 0
            paragraph_count = 0
            heading_count = 0

            for block in doc.element.body:
                if block.tag.endswith("tbl"):
                    table_count += 1
                elif block.tag.endswith("p"):
                    paragraph_count += 1
                    para = docx.text.paragraph.Paragraph(block, doc)
                    if para.style.name.startswith("Heading"):
                        heading_count += 1

            return {
                "valid": True,
                "table_count": table_count,
                "paragraph_count": paragraph_count,
                "heading_count": heading_count,
                "sections": len(doc.sections),
            }

        except Exception as e:
            return {
                "valid": False,
                "error": str(e),
                "table_count": 0,
                "paragraph_count": 0,
                "heading_count": 0,
                "sections": 0,
            }


class AsyncWordReader:
    """
    Async version of WordReader for improved performance with concurrent file processing.

    Uses ThreadPoolExecutor to handle I/O-bound operations asynchronously,
    allowing better resource utilization when processing multiple documents.
    """

    def __init__(self, max_workers: int = 4):
        """
        Initialize async word reader.

        Args:
            max_workers: Maximum number of worker threads for concurrent processing
        """
        self.executor = ThreadPoolExecutor(max_workers=max_workers)
        self._sync_reader = WordReader()

    async def read_document_async(
        self, file_path: str
    ) -> List[Tuple[pd.DataFrame, Optional[str]]]:
        """
        Read Word document asynchronously.

        Args:
            file_path: Path to Word document

        Returns:
            List[Tuple[pd.DataFrame, Optional[str]]]: List of (table_df, heading) pairs
        """
        loop = asyncio.get_event_loop()
        return await loop.run_in_executor(
            self.executor, self._sync_reader.read_tables_with_headings, file_path
        )

    async def validate_document_structure_async(self, file_path: str) -> Dict[str, Any]:
        """
        Validate Word document structure asynchronously.

        Args:
            file_path: Path to Word document

        Returns:
            Dict with validation results
        """
        loop = asyncio.get_event_loop()
        return await loop.run_in_executor(
            self.executor, self._sync_reader.validate_document_structure, file_path
        )

    def shutdown(self, wait: bool = True) -> None:
        """
        Shutdown the thread pool executor.
    async def __aenter__(self):
        \
\\Async
context
manager
entry.\\\
        return self

    async def __aexit__(self, exc_type, exc_val, exc_tb):
        \\\Async
context
manager
exit.\\\
        self.shutdown()



        Args:
            wait: If True, wait for all pending tasks to complete
        """
        self.executor.shutdown(wait=wait)

    def __enter__(self):
        """Context manager entry."""
        return self

    def __exit__(self, exc_type, exc_val, exc_tb):
        """Context manager exit - shutdown executor."""
        self.shutdown(wait=True)
