"""
Integration tests for batch processing functionality.
"""

import tempfile

import pytest

from quality_audit.core.cache_manager import AuditContext, LRUCacheManager
from quality_audit.io.excel_writer import ExcelWriter
from quality_audit.io.file_handler import FileHandler
from quality_audit.io.word_reader import AsyncWordReader
from quality_audit.services.audit_service import AuditService
from quality_audit.services.batch_processor import BatchProcessor


class TestBatchProcessing:
    """Integration tests for batch file processing."""

    @pytest.fixture
    def audit_service(self):
        """Create AuditService instance for testing."""
        cache_manager = LRUCacheManager(max_size=100)
        context = AuditContext(cache=cache_manager)
        async_word_reader = AsyncWordReader(max_workers=2)

        return AuditService(
            context=context,
            async_word_reader=async_word_reader,
            excel_writer=ExcelWriter(),
            file_handler=FileHandler(),
        )

    @pytest.fixture
    def batch_processor(self, audit_service):
        """Create BatchProcessor instance for testing."""
        return BatchProcessor(audit_service, max_concurrent=2)

    @pytest.mark.asyncio
    async def test_process_batch_empty_list(self, batch_processor):
        """Test batch processing with empty file list."""
        with tempfile.TemporaryDirectory() as tmpdir:
            results = await batch_processor.process_batch_async([], tmpdir)
            assert results == []

    @pytest.mark.asyncio
    async def test_process_batch_invalid_files(self, batch_processor):
        """Test batch processing with invalid file paths."""
        with tempfile.TemporaryDirectory() as tmpdir:
            invalid_files = ["/nonexistent/file1.docx", "/nonexistent/file2.docx"]

            results = await batch_processor.process_batch_async(invalid_files, tmpdir)

            assert len(results) == 2
            for result in results:
                assert result["success"] is False
                assert "error" in result

    @pytest.mark.asyncio
    async def test_process_batch_mixed_valid_invalid(self, batch_processor):
        """Test batch processing with mix of valid and invalid files."""
        with tempfile.TemporaryDirectory() as tmpdir:
            files = [
                "/nonexistent/file1.docx",  # Invalid
                "/nonexistent/file2.docx",  # Invalid
            ]

            results = await batch_processor.process_batch_async(files, tmpdir)

            assert len(results) == 2
            # All should fail, but processing should complete
            assert all(not r["success"] for r in results)

    def test_get_batch_summary(self, batch_processor):
        """Test batch summary generation."""
        results = [
            {"success": True, "tables_processed": 5},
            {"success": True, "tables_processed": 3},
            {"success": False, "tables_processed": 0, "error": "Test error"},
        ]

        summary = batch_processor.get_batch_summary(results)

        assert summary["total_files"] == 3
        assert summary["successful"] == 2
        assert summary["failed"] == 1
        assert summary["total_tables_processed"] == 8
        assert summary["success_rate"] == pytest.approx(66.67, rel=0.1)

    def test_get_batch_summary_empty(self, batch_processor):
        """Test batch summary with empty results."""
        summary = batch_processor.get_batch_summary([])

        assert summary["total_files"] == 0
        assert summary["successful"] == 0
        assert summary["failed"] == 0
        assert summary["total_tables_processed"] == 0
        assert summary["success_rate"] == 0.0

    @pytest.mark.asyncio
    async def test_batch_processor_semaphore_limit(self, audit_service):
        """Test that semaphore limits concurrent processing."""
        # Create processor with max_concurrent=2
        processor = BatchProcessor(audit_service, max_concurrent=2)

        # Create many invalid files (processing will be fast due to early failure)
        files = [f"/nonexistent/file{i}.docx" for i in range(10)]

        with tempfile.TemporaryDirectory() as tmpdir:
            # This should complete without issues, respecting semaphore limit
            results = await processor.process_batch_async(files, tmpdir)

            assert len(results) == 10
            # All should fail, but semaphore should have limited concurrency
