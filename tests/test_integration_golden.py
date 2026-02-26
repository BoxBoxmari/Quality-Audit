"""
Phase 6: Integration golden test — full pipeline on sample DOCX; assert summary sheet has Heading Source, Classifier Reason, Assertions Count.
"""

import pytest
from openpyxl import load_workbook

from quality_audit.core.cache_manager import AuditContext, LRUCacheManager
from quality_audit.io.excel_writer import ExcelWriter
from quality_audit.io.file_handler import FileHandler
from quality_audit.io.word_reader import AsyncWordReader
from quality_audit.services.audit_service import AuditService


class TestIntegrationGolden:
    """Run pipeline on sample_word_file; verify summary sheet metadata columns."""

    @pytest.fixture
    def audit_service(self):
        cache_manager = LRUCacheManager(max_size=1000)
        context = AuditContext(cache=cache_manager)
        async_word_reader = AsyncWordReader(max_workers=4)
        return AuditService(
            context=context,
            async_word_reader=async_word_reader,
            excel_writer=ExcelWriter(),
            file_handler=FileHandler(),
        )

    @pytest.mark.asyncio
    async def test_summary_sheet_has_heading_classifier_assertions(
        self, audit_service, sample_word_file, tmp_path
    ):
        excel_path = tmp_path / "golden_output.xlsx"
        result = await audit_service.process_document_async(
            str(sample_word_file), str(excel_path)
        )
        assert result["success"] is True, result.get("error")
        assert excel_path.exists()

        wb = load_workbook(excel_path)
        assert "Tổng hợp kiểm tra" in wb.sheetnames
        ws = wb["Tổng hợp kiểm tra"]
        assert (
            ws.max_row >= 2
        ), "Summary sheet should have header + at least one data row"

        # Row 1 = headers. Columns: 25=Heading Source, 29=Classifier Reason, 31=Assertions Count
        assert ws.cell(row=1, column=25).value == "Heading Source"
        assert ws.cell(row=1, column=29).value == "Classifier Reason"
        assert ws.cell(row=1, column=31).value == "Assertions Count"
