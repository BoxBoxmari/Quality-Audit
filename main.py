#!/usr/bin/env python3
"""
Quality Audit - Financial Statement Validation Tool

Main entry point for the application.
"""
import argparse
import asyncio
import multiprocessing
import sys
from pathlib import Path
from typing import List

from quality_audit.core.cache_manager import AuditContext, LRUCacheManager
from quality_audit.core.exceptions import QualityAuditError
from quality_audit.io.excel_writer import ExcelWriter
from quality_audit.io.file_handler import FileHandler
from quality_audit.io.word_reader import AsyncWordReader
from quality_audit.services.audit_service import AuditService
from quality_audit.services.batch_processor import BatchProcessor


def main():
    """Main application entry point."""
    parser = argparse.ArgumentParser(
        description="Quality Audit - Financial Statement Validation Tool",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
  python main.py /path/to/input/folder
  python main.py --help

Description:
  Tool sẽ tự động tìm tất cả file .docx trong folder được chỉ định
  và xử lý chúng với performance tối ưu (concurrency tự động).
  Kết quả luôn được lưu trong folder 'results' trong thư mục tool.
        """,
    )

    parser.add_argument(
        "input_folder", help="Path to input folder containing .docx files to process"
    )

    parser.add_argument(
        "--cache-size",
        type=int,
        default=1000,
        help="Maximum cache size (default: 1000)",
    )

    parser.add_argument(
        "--log-level",
        choices=["DEBUG", "INFO", "WARNING", "ERROR"],
        default="INFO",
        help="Logging level (default: INFO)",
    )

    args = parser.parse_args()

    # Validate input folder
    input_folder = Path(args.input_folder)
    if not input_folder.exists() or not input_folder.is_dir():
        print(
            f"ERROR: Input folder does not exist or is not a directory: {input_folder}"
        )
        sys.exit(1)

    # Find all .docx files in input folder
    docx_files = _find_docx_files(input_folder)
    if not docx_files:
        print(f"ERROR: No .docx files found in folder: {input_folder}")
        sys.exit(1)

    print(f"Found {len(docx_files)} .docx files in {input_folder}")
    for file_path in docx_files:
        print(f"  {file_path.name}")

    # Setup output directory (always in tool's results folder)
    output_dir = _create_output_dir()

    # Calculate optimal concurrency
    max_concurrent = _get_optimal_concurrency()

    print(f"Using optimal concurrency: {max_concurrent} workers")
    print(f"Results will be saved to: {output_dir} (tool's results folder)")

    # Initialize components with optimal settings
    cache_manager = LRUCacheManager(max_size=args.cache_size)
    context = AuditContext(cache=cache_manager)
    async_word_reader = AsyncWordReader(max_workers=max_concurrent)

    audit_service = AuditService(
        context=context,
        async_word_reader=async_word_reader,
        excel_writer=ExcelWriter(),
        file_handler=FileHandler(),
    )

    # Process all files with optimal performance
    try:
        batch_processor = BatchProcessor(audit_service, max_concurrent=max_concurrent)

        print("\nStarting batch processing with maximum performance...")
        print("=" * 60)

        results = asyncio.run(
            batch_processor.process_batch_async(docx_files, str(output_dir))
        )

        # Display results
        _display_batch_results(results, output_dir)

    except KeyboardInterrupt:
        print("\nProcessing cancelled by user")
        sys.exit(130)
    except Exception as e:
        print(f"\nERROR: Batch processing failed: {e}")
        sys.exit(1)

    except QualityAuditError as e:
        print(f"Quality Audit error: {e}")
        sys.exit(1)
    except Exception as e:
        print(f"Unexpected error: {e}")
        sys.exit(1)


def _find_docx_files(folder_path: Path) -> List[Path]:
    """
    Find all .docx files in the specified folder and subfolders.

    Args:
        folder_path: Path to the folder to search

    Returns:
        List of Path objects for all .docx files found
    """
    docx_files = []
    for file_path in folder_path.rglob("*.docx"):
        if file_path.is_file():
            docx_files.append(file_path)

    # Sort by name for consistent processing order
    return sorted(docx_files, key=lambda x: x.name)


def _create_output_dir() -> Path:
    """
    Create output directory for results.

    Always creates a 'results' folder in the current working directory
    (where the tool is located).

    Returns:
        Path to output directory
    """
    # Always use ./results folder in tool's directory
    output_dir = Path.cwd() / "results"
    output_dir.mkdir(parents=True, exist_ok=True)
    return output_dir


def _get_optimal_concurrency() -> int:
    """
    Calculate optimal concurrency based on system capabilities.

    Uses CPU count with reasonable limits to avoid resource exhaustion.

    Returns:
        Optimal number of concurrent workers
    """
    cpu_count = multiprocessing.cpu_count()

    # Use min of CPU cores and reasonable upper limit
    # Most I/O bound workloads benefit from 2-4x CPU cores
    optimal = min(cpu_count * 2, 8)

    # Ensure at least 2 workers for meaningful concurrency
    return max(optimal, 2)


def _display_batch_results(results: List[dict], output_dir: Path) -> None:
    """
    Display batch processing results in a user-friendly format.

    Args:
        results: List of processing results
        output_dir: Output directory path
    """
    # Generate summary
    total_files = len(results)
    successful = sum(1 for r in results if r.get("success", False))
    failed = total_files - successful
    total_tables = sum(r.get("tables_processed", 0) for r in results)

    # Display summary
    print("\n" + "=" * 60)
    print("BATCH PROCESSING RESULTS")
    print("=" * 60)
    print(f"Total files processed: {total_files}")
    print(f"Successful: {successful}")
    print(f"Failed: {failed}")
    print(f"Total tables processed: {total_tables}")
    print(".1f")
    print(f"Results saved to: {output_dir}")
    print("=" * 60)

    # Display individual results
    print("\nDetailed Results:")
    for result in results:
        status = "SUCCESS" if result.get("success", False) else "FAILED"
        input_file = Path(result.get("input_file", "Unknown")).name
        tables = result.get("tables_processed", 0)

        print(f"  {status} {input_file}: {tables} tables")

        if not result.get("success", False):
            error_msg = result.get("error", "Unknown error")
            print(f"      Error: {error_msg}")

    # Final status
    if failed == 0:
        print("\nAll files processed successfully!")
    else:
        print(f"\n{failed} file(s) failed processing")
        print("Check individual file errors above for details")


if __name__ == "__main__":
    main()
