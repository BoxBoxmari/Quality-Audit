"""
Integration tests for async processing functionality.
"""

import tempfile
from pathlib import Path

import pytest

from quality_audit.core.cache_manager import AuditContext, LRUCacheManager
from quality_audit.io.excel_writer import ExcelWriter
from quality_audit.io.file_handler import FileHandler
from quality_audit.io.word_reader import AsyncWordReader
from quality_audit.services.audit_service import AuditService


class TestAsyncProcessing:
    """Integration tests for async document processing."""

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

    @pytest.mark.asyncio
    async def test_process_document_async_invalid_file(self, audit_service):
        """Test async processing with invalid file path."""
        with tempfile.TemporaryDirectory() as tmpdir:
            output_path = Path(tmpdir) / "output.xlsx"
            result = await audit_service.process_document_async(
                "/nonexistent/file.docx", str(output_path)
            )

            assert result["success"] is False
            assert "error" in result
            assert result["tables_processed"] == 0

    @pytest.mark.asyncio
    async def test_async_word_reader_context_manager(self):
        """Test AsyncWordReader as context manager."""
        async_reader = AsyncWordReader(max_workers=2)

        async with async_reader:
            # Should be able to use reader
            assert async_reader.executor is not None

        # After context exit, executor should be shutdown
        # (We can't directly check this, but no exception should occur)

    @pytest.mark.asyncio
    async def test_async_word_reader_shutdown(self):
        """Test AsyncWordReader shutdown."""
        async_reader = AsyncWordReader(max_workers=2)

        # Use reader
        assert async_reader.executor is not None

        # Shutdown
        async_reader.shutdown(wait=True)

        # Should not raise exception on subsequent shutdown
        async_reader.shutdown(wait=False)

    def test_async_service_backward_compatibility(self):
        """Test that sync audit_document still works."""
        cache_manager = LRUCacheManager(max_size=100)
        context = AuditContext(cache=cache_manager)

        service = AuditService(
            context=context, excel_writer=ExcelWriter(), file_handler=FileHandler()
        )

        # Should have sync word_reader by default
        assert service.word_reader is not None
        assert hasattr(service, "audit_document")
