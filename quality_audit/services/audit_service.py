"""
Main audit service orchestrating the entire validation workflow.
"""

from typing import Any, Dict, List, Optional, Tuple

import pandas as pd

from ..config.constants import TABLES_WITHOUT_TOTAL
from ..core.cache_manager import (AuditContext, LRUCacheManager,
                                  cross_check_marks)
from ..core.exceptions import (FileProcessingError, SecurityError,
                               ValidationError)
from ..io.excel_writer import ExcelWriter
from ..io.file_handler import FileHandler
from ..io.word_reader import AsyncWordReader, WordReader
from .base_service import BaseService


class AuditService(BaseService):
    """
    Main service for orchestrating financial statement auditing.

    Coordinates Word reading, validation, and Excel report generation.
    """

    def __init__(
        self,
        context: Optional[AuditContext] = None,
        cache_manager: Optional[LRUCacheManager] = None,
        word_reader: Optional[WordReader] = None,
        async_word_reader: Optional[AsyncWordReader] = None,
        excel_writer: Optional[ExcelWriter] = None,
        file_handler: Optional[FileHandler] = None,
    ):
        """
        Initialize audit service with dependencies.

        Args:
            context: Audit context with cache and marks (preferred over cache_manager)
            cache_manager: Cache for cross-referencing data (deprecated, use context instead)
            word_reader: Word document reader (sync)
            async_word_reader: Async word document reader for concurrent processing
            excel_writer: Excel report writer
            file_handler: Secure file handler
        """
        # Initialize base service with context
        super().__init__(context=context, cache_manager=cache_manager)

        self.word_reader = word_reader or WordReader()
        self.async_word_reader = async_word_reader
        self.excel_writer = excel_writer or ExcelWriter()
        self.file_handler = file_handler or FileHandler()

        # Keep cache_manager for backward compatibility (deprecated)
        self.cache_manager = self.context.cache

    def audit_document(self, word_path: str, excel_path: str) -> Dict[str, Any]:
        """
        Execute complete audit workflow.

        Args:
            word_path: Path to Word document
            excel_path: Path to output Excel file

        Returns:
            Dict with audit results and metadata
        """
        try:
            # Clear cache and marks at start of audit run using context
            self.context.clear()
            # Also clear global marks for backward compatibility
            cross_check_marks.clear()

            # Validate inputs with proper error handling
            if not self.file_handler.validate_path(word_path):
                raise SecurityError(f"Invalid or unsafe Word file path: {word_path}")

            # Read tables from Word document
            table_heading_pairs = self.word_reader.read_tables_with_headings(word_path)

            if not table_heading_pairs:
                raise ValueError("No tables found in Word document")

            # Validate all tables
            results = self._validate_tables(table_heading_pairs)

            # Generate Excel report
            self._generate_report(table_heading_pairs, results, excel_path)

            # Cache and marks are cleared at start of next run, but clear here for
            # safety
            self.context.clear()
            cross_check_marks.clear()

            return {
                "success": True,
                "tables_processed": len(table_heading_pairs),
                "results": results,
                "output_path": excel_path,
            }

        except (SecurityError, FileProcessingError, ValidationError) as e:
            # Return error result for known exceptions
            return {
                "success": False,
                "error": str(e),
                "error_type": type(e).__name__,
                "tables_processed": 0,
                "results": [],
                "output_path": None,
            }
        except Exception as e:
            # Wrap unknown exceptions
            return {
                "success": False,
                "error": f"Unexpected error during audit: {str(e)}",
                "error_type": "QualityAuditError",
                "tables_processed": 0,
                "results": [],
                "output_path": None,
            }

    def _validate_tables(
        self, table_heading_pairs: List[Tuple[pd.DataFrame, Optional[str]]]
    ) -> List[Dict]:
        """
        Validate all tables using appropriate validators.

        Args:
            table_heading_pairs: List of (table_df, heading) tuples

        Returns:
            List of validation results
        """
        results = []

        for table, heading in table_heading_pairs:
            try:
                # Determine validation approach based on heading and content
                result = self._validate_single_table(table, heading)
                results.append(
                    result.to_dict() if hasattr(result, "to_dict") else result
                )

            except Exception as e:
                # Handle validation errors gracefully
                error_result = {
                    "status": f"ERROR: Lỗi validation: {str(e)}",
                    "marks": [],
                    "cross_ref_marks": [],
                }
                results.append(error_result)

        return results

    def _validate_single_table(
        self, table: pd.DataFrame, heading: Optional[str]
    ) -> Dict:
        """
        Validate a single table using appropriate validator.

        Args:
            table: Table DataFrame
            heading: Table heading

        Returns:
            Dict with validation results
        """
        from ..core.validators.factory import ValidatorFactory

        # Get appropriate validator
        validator = ValidatorFactory.get_validator(table, heading)

        # Validate table
        result = validator.validate(table, heading)

        return result.to_dict()

    def _is_table_without_total(self, table: pd.DataFrame, heading_lower: str) -> bool:
        """
        Check if table should be skipped from total validation.

        Args:
            table: Table DataFrame
            heading_lower: Lowercase heading

        Returns:
            bool: True if table should be skipped
        """
        # Check if heading indicates no totals expected
        if heading_lower in TABLES_WITHOUT_TOTAL:
            return True

        # Check if table has insufficient numeric data
        subset = table.iloc[2:]  # Skip header rows
        numeric_content = subset.map(
            lambda x: pd.to_numeric(
                str(x).replace(",", "").replace("(", "-").replace(")", ""),
                errors="coerce",
            )
        )
        return numeric_content.isna().all().all()

    def _validate_standard_table(self, table: pd.DataFrame, heading_lower: str) -> Dict:
        """
        Validate standard financial table.

        Args:
            table: Table DataFrame
            heading_lower: Lowercase heading

        Returns:
            Dict with validation results
        """
        # This is a simplified version - in full implementation,
        # this would delegate to specific validator classes
        return {
            "status": f'SUCCESS: Đã xử lý bảng: {heading_lower or "Không tiêu đề"}',
            "marks": [],
            "cross_ref_marks": [],
        }

    def _generate_report(
        self,
        table_heading_pairs: List[Tuple[pd.DataFrame, Optional[str]]],
        results: List[Dict],
        excel_path: str,
    ) -> None:
        """
        Generate Excel report with validation results.

        Args:
            table_heading_pairs: Table and heading pairs
            results: Validation results
            excel_path: Output Excel path
        """
        wb = self.excel_writer.create_workbook()

        # Option 2: Consolidated sheet (as in original)
        sheet_positions = self.excel_writer.write_tables_consolidated(
            wb, table_heading_pairs, results
        )
        self.excel_writer.write_summary_sheet(wb, results, sheet_positions)

        self.excel_writer.save_workbook(wb, excel_path)

        # Safe file opening (no command execution)
        self.file_handler.open_file_safely(excel_path)

    async def process_document_async(
        self, word_path: str, excel_path: str
    ) -> Dict[str, Any]:
        """
        Execute complete audit workflow asynchronously.

        This is the async version of audit_document, using AsyncWordReader
        for improved performance with concurrent file processing.

        Args:
            word_path: Path to Word document
            excel_path: Path to output Excel file

        Returns:
            Dict with audit results and metadata (same format as audit_document)
        """
        try:
            # Clear cache and marks at start of audit run using context
            self.context.clear()
            # Also clear global marks for backward compatibility
            cross_check_marks.clear()

            # Validate inputs with proper error handling
            if not self.file_handler.validate_path(word_path):
                raise SecurityError(f"Invalid or unsafe Word file path: {word_path}")

            # Use async reader - create if not provided
            async_reader = self.async_word_reader or AsyncWordReader(max_workers=4)

            # Read tables from Word document asynchronously
            async with async_reader:
                table_heading_pairs = await async_reader.read_document_async(word_path)

            if not table_heading_pairs:
                raise ValueError("No tables found in Word document")

            # Validate all tables (validation is CPU-bound, can be async in future)
            results = self._validate_tables(table_heading_pairs)

            # Generate Excel report
            self._generate_report(table_heading_pairs, results, excel_path)

            # Cache and marks are cleared at start of next run, but clear here for
            # safety
            self.context.clear()
            cross_check_marks.clear()

            return {
                "success": True,
                "tables_processed": len(table_heading_pairs),
                "results": results,
                "output_path": excel_path,
            }

        except (SecurityError, FileProcessingError, ValidationError) as e:
            # Return error result for known exceptions
            return {
                "success": False,
                "error": str(e),
                "error_type": type(e).__name__,
                "tables_processed": 0,
                "results": [],
                "output_path": None,
            }
        except Exception as e:
            # Wrap unknown exceptions
            return {
                "success": False,
                "error": f"Unexpected error during async audit: {str(e)}",
                "error_type": "QualityAuditError",
                "tables_processed": 0,
                "results": [],
                "output_path": None,
            }
