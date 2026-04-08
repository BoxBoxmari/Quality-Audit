"""
Batch processing service for concurrent file processing.

Provides infrastructure for processing multiple Word documents concurrently
with configurable concurrency limits and error handling.
"""

import asyncio
from builtins import BaseException
from pathlib import Path
from typing import Any, Callable, Dict, List, Optional, Union

from .audit_service import AuditService


class BatchProcessor:
    """
    Process multiple files concurrently with configurable concurrency limits.

    Uses asyncio.Semaphore to control the number of files processed
    simultaneously, preventing resource exhaustion.
    """

    def __init__(
        self,
        service_factory: Union[AuditService, Callable[[], AuditService]],
        max_concurrent: int = 4,
    ):
        """
        Initialize batch processor.

        Args:
            service_factory: Either an AuditService instance (legacy) or a callable
                returning a fresh AuditService per processed file.
            max_concurrent: Maximum number of files to process concurrently (default: 4)
        """
        if isinstance(service_factory, AuditService):
            # Backward compatibility: wrap static instance as a factory.
            self._service_factory: Callable[[], AuditService] = lambda: service_factory
        else:
            self._service_factory = service_factory

        # NOTE: Canonical runtime delegates into legacy/main.py which owns
        # module-level mutable globals. True parallelism is not safe without
        # process isolation or per-task isolated legacy runtime instances.
        #
        # This bugfix makes the serialization explicit by enforcing max_concurrent=1
        # (instead of silently serializing inside a lock while presenting higher
        # concurrency settings).
        self.max_concurrent = min(int(max_concurrent), 1)

        # Legacy module owns module-level mutable globals, so serialize canonical execution.
        self._legacy_lock = asyncio.Lock()

    async def process_batch_async(
        self,
        file_paths: List[str],
        output_dir: str,
        output_suffix: str = "_output.xlsx",
        on_file_complete: Optional[Callable[[Dict[str, Any]], None]] = None,
    ) -> List[Dict[str, Any]]:
        """
        Process multiple files concurrently with semaphore-based concurrency control.

        Each file is processed independently, and errors in one file do not
        affect processing of other files.

        Args:
            file_paths: List of paths to Word documents to process
            output_dir: Directory to save output Excel files
            output_suffix: Suffix to append to input filename for output (default: "_output.xlsx")

        Returns:
            List[Dict[str, Any]]: List of results from processing each file.
                                 Each result has the same format as AuditService.process_document_async()
        """
        if not file_paths:
            return []

        # Create output directory if it doesn't exist
        output_path = Path(output_dir)
        output_path.mkdir(parents=True, exist_ok=True)

        # Create semaphore to limit concurrent processing
        semaphore = asyncio.Semaphore(self.max_concurrent)

        async def process_single_file(file_path: str) -> Dict[str, Any]:
            """
            Process a single file with semaphore control.

            Args:
                file_path: Path to Word document

            Returns:
                Dict with processing results
            """
            async with semaphore:
                try:
                    # Generate output path
                    input_path = Path(file_path)
                    output_file = output_path / f"{input_path.stem}{output_suffix}"

                    service = self._service_factory()
                    # Process document asynchronously
                    result = await service.process_document_async(
                        str(file_path),
                        str(output_file),
                        legacy_lock=self._legacy_lock,  # type: ignore[arg-type]
                    )

                    # Add file path to result for tracking
                    result["input_file"] = file_path
                    result["output_file"] = str(output_file)

                    return result

                except Exception as e:
                    # Return error result for this file
                    return {
                        "success": False,
                        "error": str(e),
                        "error_type": type(e).__name__,
                        "input_file": file_path,
                        "output_file": None,
                        "tables_processed": 0,
                        "results": [],
                    }

        # Create tasks for all files
        tasks = [process_single_file(path) for path in file_paths]

        # Process all files concurrently (with semaphore limiting)
        results: List[Union[Dict[str, Any], BaseException]] = await asyncio.gather(
            *tasks, return_exceptions=True
        )

        # Handle exceptions that weren't caught in process_single_file
        processed_results: List[Dict[str, Any]] = []
        for idx, result in enumerate(results):
            if isinstance(result, Exception):
                item = {
                    "success": False,
                    "error": str(result),
                    "error_type": type(result).__name__,
                    "error_code": "BATCH_PROCESS_EXCEPTION",
                    "stage": "batch_process",
                    "input_file": file_paths[idx],
                    "output_file": None,
                    "tables_processed": 0,
                    "results": [],
                }
                processed_results.append(item)
                if on_file_complete is not None:
                    on_file_complete(item)
            elif isinstance(result, dict):
                processed_results.append(result)
                if on_file_complete is not None:
                    on_file_complete(result)

        return processed_results

    def get_batch_summary(self, results: List[Dict[str, Any]]) -> Dict[str, Any]:
        """
        Generate summary statistics from batch processing results.

        Args:
            results: List of results from process_batch_async()

        Returns:
            Dict with summary statistics
        """
        total_files = len(results)
        successful = sum(1 for r in results if r.get("success", False))
        failed = total_files - successful
        total_tables = sum(r.get("tables_processed", 0) for r in results)

        return {
            "total_files": total_files,
            "successful": successful,
            "failed": failed,
            "total_tables_processed": total_tables,
            "success_rate": (
                (successful / total_files * 100) if total_files > 0 else 0.0
            ),
        }
