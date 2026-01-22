"""
Integration tests for AuditService.
"""

import pytest
from openpyxl import load_workbook

from quality_audit.core.cache_manager import AuditContext, LRUCacheManager
from quality_audit.services.audit_service import AuditService


class TestAuditServiceIntegration:
    """Integration tests for complete audit workflow."""

    @pytest.fixture
    def audit_context(self):
        """Create audit context for testing."""
        cache = LRUCacheManager(max_size=100)
        return AuditContext(cache=cache)

    @pytest.fixture
    def audit_service(self, audit_context):
        """Create audit service instance."""
        return AuditService(context=audit_context)

    def test_full_audit_workflow(self, audit_service, sample_word_file, tmp_path):
        """
        Test complete audit workflow from Word to Excel.

        This test verifies the entire pipeline:
        1. Word document reading
        2. Table validation
        3. Excel report generation
        """
        excel_path = tmp_path / "output.xlsx"

        result = audit_service.audit_document(sample_word_file, str(excel_path))

        assert result["success"] is True
        assert result["tables_processed"] > 0
        assert excel_path.exists()

        # Verify Excel content
        wb = load_workbook(excel_path)
        assert "Tổng hợp kiểm tra" in wb.sheetnames

    def test_audit_service_with_invalid_file(self, audit_service, tmp_path):
        """Test audit service with invalid file path."""
        invalid_path = tmp_path / "nonexistent.docx"
        excel_path = tmp_path / "output.xlsx"

        result = audit_service.audit_document(str(invalid_path), str(excel_path))

        assert result["success"] is False
        assert "error" in result
        assert result["tables_processed"] == 0

    def test_audit_service_context_isolation(self, tmp_path):
        """Test that different audit contexts are isolated."""
        context1 = AuditContext(cache=LRUCacheManager(max_size=100))
        context2 = AuditContext(cache=LRUCacheManager(max_size=100))

        service1 = AuditService(context=context1)
        service2 = AuditService(context=context2)

        # Verify contexts are separate
        assert service1.context is not service2.context
        assert service1.context.cache is not service2.context.cache
