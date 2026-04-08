#!/usr/bin/env python3
"""
Quality Audit - Financial Statement Validation Tool

Main entry point for the application.
"""

import argparse
import asyncio
import json
import logging
import multiprocessing
import sys
from pathlib import Path
from typing import List, Optional

from quality_audit.config.tax_rate import TaxRateConfig
from quality_audit.core.cache_manager import AuditContext, LRUCacheManager
from quality_audit.core.exceptions import QualityAuditError
from quality_audit.io import ExcelWriter, FileHandler
from quality_audit.io.word_reader import AsyncWordReader
from quality_audit.services.audit_service import AuditService
from quality_audit.services.batch_processor import BatchProcessor


def main(argv: Optional[List[str]] = None) -> int:
    """
    Main application entry point.

    Args:
        argv: Command line arguments (default: sys.argv[1:])

    Returns:
        int: Exit code (0=success, 1=error, 2=exception, 130=cancel)
    """
    parser = argparse.ArgumentParser(
        description="Quality Audit - Financial Statement Validation Tool",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
  python -m quality_audit.cli /path/to/folder
  python -m quality_audit.cli /path/to/file.docx
  python -m quality_audit.cli /path --output-dir /custom/out
  python -m quality_audit.cli /path --tax-rate-mode all --tax-rate 20
        """,
    )

    parser.add_argument(
        "input_path",
        help="Path to input folder containing .docx files or single .docx file",
    )

    parser.add_argument(
        "--output-dir",
        type=str,
        default=None,
        help="Output directory (default: ./results in CWD)",
    )

    parser.add_argument(
        "--cache-size",
        type=int,
        default=1000,
        help="Maximum cache size (default: 1000)",
    )

    parser.add_argument(
        "--previous-output",
        type=str,
        default=None,
        help="Path to previous audit Excel output for triage data carry-forward",
    )

    parser.add_argument(
        "--log-level",
        choices=["DEBUG", "INFO", "WARNING", "ERROR"],
        default="INFO",
        help="Logging level (default: INFO)",
    )

    # Tax Rate Configuration
    parser.add_argument(
        "--tax-rate-mode",
        choices=["prompt", "all", "individual"],
        default="prompt",
        help="Tax rate resolution mode",
    )

    parser.add_argument(
        "--tax-rate",
        type=float,
        help="Tax rate percentage for 'all' mode (0-100)",
    )

    parser.add_argument(
        "--tax-rate-map",
        type=str,
        help="Path to JSON tax rate mapping file for 'individual' mode",
    )

    parser.add_argument(
        "--require-render-first",
        action="store_true",
        default=False,
        help="Abort if render-first extraction fails (no OOXML fallback)",
    )

    args = parser.parse_args(argv if argv is not None else sys.argv[1:])

    # Apply log level so validators and services emit DEBUG when requested
    log_level = getattr(logging, args.log_level.upper(), logging.INFO)
    logging.basicConfig(
        level=log_level,
        format="%(levelname)s: %(name)s: %(message)s",
        force=True,
    )
    logging.getLogger("quality_audit").setLevel(log_level)

    try:
        from quality_audit import BUILD_STAMP

        print(f"Quality Audit BUILD_STAMP={BUILD_STAMP}")
        logger_root = logging.getLogger("quality_audit")
        logger_root.info("BUILD_STAMP=%s", BUILD_STAMP)

        # Validate input path
        input_path = Path(args.input_path)
        if not input_path.exists():
            print(f"ERROR: Input path does not exist: {input_path}")
            return 1

        docx_files: List[Path] = []
        base_path: Path

        if input_path.is_file():
            if input_path.suffix.lower() != ".docx":
                print(f"ERROR: Input file must be a .docx file: {input_path}")
                return 1
            docx_files = [input_path]
            base_path = input_path.parent
        elif input_path.is_dir():
            docx_files = _find_docx_files(input_path)
            base_path = input_path
            if not docx_files:
                print(f"ERROR: No .docx files found in folder: {input_path}")
                return 1
        else:
            print(f"ERROR: Invalid input path type: {input_path}")
            return 1

        if not args.tax_rate_mode:
            # Should not happen due to default="prompt", but safe check
            pass

        # Validate Tax Config
        tax_config = _build_tax_config(args)

        print(f"Found {len(docx_files)} .docx files to process")
        for file_path in docx_files:
            print(f"  {file_path.name}")

        # Setup output directory
        output_dir = _resolve_output_dir(args.output_dir)
        print(f"Output directory: {output_dir}")

        # Calculate optimal concurrency
        max_concurrent = _get_optimal_concurrency()
        print(f"Using concurrency: {max_concurrent} workers")

        # Initialize batch components.
        # BatchProcessor sẽ gọi service_factory để tạo service mới cho mỗi file,
        # đảm bảo không có state/cache bleed giữa các file cùng một lần chạy.
        async_word_reader = AsyncWordReader(max_workers=max_concurrent)

        def _make_audit_service() -> AuditService:
            cache_manager = LRUCacheManager(max_size=args.cache_size)
            context = AuditContext(
                cache=cache_manager, tax_rate_config=tax_config, base_path=base_path
            )
            return AuditService(
                context=context,
                async_word_reader=async_word_reader,
                excel_writer=ExcelWriter(previous_output_path=args.previous_output),
                file_handler=FileHandler(),
            )

        batch_processor = BatchProcessor(
            _make_audit_service, max_concurrent=max_concurrent
        )

        print("\nStarting batch processing...")
        print("=" * 60)

        # We pass output_dir as str because BatchProcessor expects it
        results = asyncio.run(
            batch_processor.process_batch_async(
                [str(f) for f in docx_files], str(output_dir)
            )
        )

        # Display results
        _display_batch_results(results, output_dir)

        # Check for failures
        failed = sum(1 for r in results if not r.get("success", False))
        return 1 if failed > 0 else 0

    except ValueError:
        logger = logging.getLogger("quality_audit")
        logger.debug("Configuration error during CLI execution", exc_info=True)
        print("Configuration Error: Invalid arguments or configuration.")
        return 1
    except KeyboardInterrupt:
        logging.getLogger("quality_audit").exception("Processing cancelled by user")
        print("\nProcessing cancelled by user")
        return 130
    except QualityAuditError:
        logger = logging.getLogger("quality_audit")
        logger.debug("Quality Audit domain error during processing", exc_info=True)
        print("Quality Audit error: Processing failed. See logs for details.")
        return 1
    except Exception:
        logger = logging.getLogger("quality_audit")
        logger.debug("Unexpected CLI exception", exc_info=True)
        print("\nERROR: Unexpected error during processing.")
        return 2


def _build_tax_config(args) -> TaxRateConfig:
    """Build and validate TaxRateConfig from CLI args."""
    mode = args.tax_rate_mode
    config = TaxRateConfig(mode=mode)

    if mode == "all":
        if args.tax_rate is None:
            raise ValueError("Mode 'all' requires --tax-rate")
        if not (0 <= args.tax_rate <= 100):
            raise ValueError("Tax rate must be between 0 and 100")
        config.all_rate = float(args.tax_rate) / 100.0  # Convert to decimal 0.25

    elif mode == "individual":
        if not args.tax_rate_map:
            raise ValueError("Mode 'individual' requires --tax-rate-map")
        map_path = Path(args.tax_rate_map)
        if not map_path.exists():
            raise ValueError(f"Tax rate map file not found: {map_path}")

        try:
            with open(map_path, encoding="utf-8") as f:
                data = json.load(f)
                config.map_data = {}
                # Normalize keys and values
                if "default" in data:
                    config.default_rate = float(data["default"]) / 100.0

                # Check for "files" key or flat structure? User plan implied flat structure or "files" key.
                # User plan: "resolve from map_data... then basename... then default"
                # Let's assume the JSON passed matches what GUI generates.
                # Re-reading plan: "files": { ... }
                files_map = data.get("files", {})
                for k, v in files_map.items():
                    config.map_data[k] = float(v) / 100.0

                # Store default as well if needed in map_data for lookup convenience
                if "default" in data:
                    config.map_data["default"] = config.default_rate

        except json.JSONDecodeError as err:
            raise ValueError(f"Invalid JSON in tax rate map: {map_path}") from err

    return config


def _find_docx_files(folder_path: Path) -> List[Path]:
    """Find all .docx files recursively."""
    docx_files = []
    for file_path in folder_path.rglob("*.docx"):
        if file_path.is_file():
            docx_files.append(file_path)
    return sorted(docx_files, key=lambda x: x.name)


def _resolve_output_dir(custom_path: Optional[str]) -> Path:
    """Resolve API output directory."""
    path = Path(custom_path) if custom_path else Path.cwd() / "results"

    path.mkdir(parents=True, exist_ok=True)
    return path


def _get_optimal_concurrency() -> int:
    """Calculate concurrency."""
    try:
        cpu_count = multiprocessing.cpu_count()
        optimal = min(cpu_count * 2, 8)
        return max(optimal, 2)
    except Exception:
        return 2


def _display_batch_results(results: List[dict], output_dir: Path) -> None:
    """Display summary."""
    total_files = len(results)
    successful = sum(1 for r in results if r.get("success", False))
    failed = total_files - successful
    total_tables = sum(r.get("tables_processed", 0) for r in results)

    print("\n" + "=" * 60)
    print("BATCH PROCESSING RESULTS")
    print("=" * 60)
    print(f"Total files processed: {total_files}")
    print(f"Successful: {successful}")
    print(f"Failed: {failed}")
    print(f"Total tables processed: {total_tables}")
    print(f"Results saved to: {output_dir}")
    print("=" * 60)

    print("\nDetailed Results:")
    for result in results:
        status = "SUCCESS" if result.get("success", False) else "FAILED"
        input_file = Path(result.get("input_file", "Unknown")).name
        tables = result.get("tables_processed", 0)
        print(f"  {status} {input_file}: {tables} tables")
        if not result.get("success", False):
            print(f"      Error: {result.get('error', 'Unknown')}")


if __name__ == "__main__":
    sys.exit(main())
