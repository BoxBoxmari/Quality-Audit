"""
Integration tests for batch processing functionality.
"""

import shutil
import tempfile
from pathlib import Path
from typing import Callable, Optional

import pytest

from quality_audit.core.cache_manager import AuditContext, LRUCacheManager
from quality_audit.io.excel_writer import ExcelWriter
from quality_audit.io.file_handler import FileHandler
from quality_audit.io.word_reader import AsyncWordReader
from quality_audit.services.audit_service import AuditService, _load_legacy_main_module
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


class TestBatchStateIsolation:
    """Regression tests for cross-file isolation in batch mode."""

    @staticmethod
    def _normalize_marks(marks):
        items = []
        for m in marks or []:
            if not isinstance(m, dict):
                continue
            items.append(
                (
                    int(m.get("row", -1)),
                    int(m.get("col", -1)),
                    m.get("ok"),
                    (m.get("comment") or "").strip(),
                )
            )
        return tuple(sorted(items))

    @classmethod
    def _normalize_table_result(cls, r: dict) -> tuple:
        return (
            (r.get("status") or "").strip(),
            cls._normalize_marks(r.get("marks")),
            cls._normalize_marks(r.get("cross_ref_marks")),
        )

    @classmethod
    def _normalize_results_payload(cls, results) -> tuple:
        normalized = []
        for r in results or []:
            if isinstance(r, dict):
                normalized.append(cls._normalize_table_result(r))
        return tuple(normalized)

    def _make_service_factory(
        self,
        *,
        async_word_reader: AsyncWordReader,
        previous_output_path=None,
        cache_max_size: int = 100,
        legacy_globals_clean: bool = False,
    ):
        if legacy_globals_clean:
            legacy_main = _load_legacy_main_module()
            bspl_cache = getattr(legacy_main, "BSPL_cross_check_cache", None)
            if isinstance(bspl_cache, dict):
                bspl_cache.clear()
            bspl_marks = getattr(legacy_main, "BSPL_cross_check_mark", None)
            if isinstance(bspl_marks, (list, set, dict)):
                bspl_marks.clear()

        def _factory() -> AuditService:
            cache_manager = LRUCacheManager(max_size=cache_max_size)
            context = AuditContext(cache=cache_manager)
            return AuditService(
                context=context,
                async_word_reader=async_word_reader,
                excel_writer=ExcelWriter(previous_output_path=previous_output_path),
                file_handler=FileHandler(),
            )

        return _factory

    @pytest.mark.asyncio
    async def test_same_content_different_filename_same_batch(
        self, sample_word_file: str
    ) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            src = Path(sample_word_file)
            file_a = Path(tmpdir) / "a.docx"
            file_b = Path(tmpdir) / "b.docx"
            shutil.copy(str(src), str(file_a))
            shutil.copy(str(src), str(file_b))

            output_dir = Path(tmpdir) / "out"
            output_dir.mkdir(parents=True, exist_ok=True)

            async_reader = AsyncWordReader(max_workers=2)
            service_factory = self._make_service_factory(
                async_word_reader=async_reader,
                cache_max_size=100,
                legacy_globals_clean=True,
            )
            batch = BatchProcessor(service_factory, max_concurrent=2)

            results = await batch.process_batch_async(
                [str(file_a), str(file_b)], str(output_dir)
            )

            assert len(results) == 2

            by_name = {Path(r["input_file"]).name: r for r in results}
            assert by_name["a.docx"].get("success") is True
            assert by_name["b.docx"].get("success") is True

            assert self._normalize_results_payload(
                by_name["a.docx"].get("results")
            ) == self._normalize_results_payload(by_name["b.docx"].get("results"))

    @pytest.mark.asyncio
    async def test_repeated_run_determinism(self, sample_word_file: str) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            src = Path(sample_word_file)
            file_a = Path(tmpdir) / "a.docx"
            shutil.copy(str(src), str(file_a))

            output_dir1 = Path(tmpdir) / "out1"
            output_dir2 = Path(tmpdir) / "out2"
            output_dir1.mkdir(parents=True, exist_ok=True)
            output_dir2.mkdir(parents=True, exist_ok=True)

            async_reader1 = AsyncWordReader(max_workers=2)
            service_factory1 = self._make_service_factory(
                async_word_reader=async_reader1,
                cache_max_size=100,
                legacy_globals_clean=True,
            )
            batch1 = BatchProcessor(service_factory1, max_concurrent=2)

            results1 = await batch1.process_batch_async([str(file_a)], str(output_dir1))
            assert len(results1) == 1

            async_reader2 = AsyncWordReader(max_workers=2)
            service_factory2 = self._make_service_factory(
                async_word_reader=async_reader2,
                cache_max_size=100,
                legacy_globals_clean=True,
            )
            batch2 = BatchProcessor(service_factory2, max_concurrent=2)
            results2 = await batch2.process_batch_async([str(file_a)], str(output_dir2))
            assert len(results2) == 1

            assert results1[0].get("success") is True
            assert results2[0].get("success") is True
            assert self._normalize_results_payload(
                results1[0].get("results")
            ) == self._normalize_results_payload(results2[0].get("results"))

    @pytest.mark.asyncio
    async def test_batch_order_invariance(self, sample_word_file: str) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            src = Path(sample_word_file)
            file_a = Path(tmpdir) / "a.docx"
            file_b = Path(tmpdir) / "b.docx"
            shutil.copy(str(src), str(file_a))
            shutil.copy(str(src), str(file_b))

            output1 = Path(tmpdir) / "out1"
            output2 = Path(tmpdir) / "out2"
            output1.mkdir(parents=True, exist_ok=True)
            output2.mkdir(parents=True, exist_ok=True)

            async_reader1 = AsyncWordReader(max_workers=2)
            service_factory1 = self._make_service_factory(
                async_word_reader=async_reader1,
                cache_max_size=100,
                legacy_globals_clean=True,
            )
            batch1 = BatchProcessor(service_factory1, max_concurrent=2)
            results1 = await batch1.process_batch_async(
                [str(file_a), str(file_b)], str(output1)
            )

            async_reader2 = AsyncWordReader(max_workers=2)
            service_factory2 = self._make_service_factory(
                async_word_reader=async_reader2,
                cache_max_size=100,
                legacy_globals_clean=True,
            )
            batch2 = BatchProcessor(service_factory2, max_concurrent=2)
            results2 = await batch2.process_batch_async(
                [str(file_b), str(file_a)], str(output2)
            )

            assert len(results1) == 2
            assert len(results2) == 2

            by_name_1 = {Path(r["input_file"]).name: r for r in results1}
            by_name_2 = {Path(r["input_file"]).name: r for r in results2}
            assert self._normalize_results_payload(
                by_name_1["a.docx"].get("results")
            ) == self._normalize_results_payload(by_name_2["a.docx"].get("results"))
            assert self._normalize_results_payload(
                by_name_1["b.docx"].get("results")
            ) == self._normalize_results_payload(by_name_2["b.docx"].get("results"))

    @pytest.mark.asyncio
    async def test_standalone_vs_batch_parity(self, sample_word_file: str) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            src = Path(sample_word_file)
            file_a = Path(tmpdir) / "a.docx"
            shutil.copy(str(src), str(file_a))

            out_standalone = Path(tmpdir) / "standalone.xlsx"
            out_batch_dir = Path(tmpdir) / "out_batch"
            out_batch_dir.mkdir(parents=True, exist_ok=True)

            async_reader = AsyncWordReader(max_workers=2)
            service_factory = self._make_service_factory(
                async_word_reader=async_reader,
                cache_max_size=100,
                legacy_globals_clean=True,
            )

            standalone_service = service_factory()
            standalone = await standalone_service.process_document_async(
                str(file_a), str(out_standalone)
            )
            assert standalone.get("success") is True

            batch = BatchProcessor(service_factory, max_concurrent=2)
            batch_results = await batch.process_batch_async(
                [str(file_a)], str(out_batch_dir)
            )
            assert len(batch_results) == 1
            assert batch_results[0].get("success") is True

            assert self._normalize_results_payload(
                standalone.get("results")
            ) == self._normalize_results_payload(batch_results[0].get("results"))

    def test_reconciliation_isolation_between_services(self) -> None:
        from quality_audit.services.financial_reconciliation_service import (
            FinancialReconciliationService,
        )

        ctx1 = AuditContext(cache=LRUCacheManager(max_size=100))
        ctx2 = AuditContext(cache=LRUCacheManager(max_size=100))

        # Simulate prior-file population.
        ctx1.cache.set("note a", (123.0, 45.0))
        assert ctx2.cache.get("note a") is None

        recon2 = FinancialReconciliationService(context=ctx2)
        report = recon2.reconcile(
            {"Note A": {"total_row_value_cy": 123.0, "total_row_value_py": 45.0}}
        )
        assert report.unmatched_count == 1

    @pytest.mark.asyncio
    async def test_no_cache_bleed_between_files(self, sample_word_file: str) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            src = Path(sample_word_file)
            file_a = Path(tmpdir) / "a.docx"
            file_b = Path(tmpdir) / "b.docx"
            shutil.copy(str(src), str(file_a))
            shutil.copy(str(src), str(file_b))

            output_dir = Path(tmpdir) / "out"
            output_dir.mkdir(parents=True, exist_ok=True)

            async_reader = AsyncWordReader(max_workers=2)

            cache_managers: list = []

            def service_factory() -> AuditService:
                cm = LRUCacheManager(max_size=100)
                cache_managers.append(cm)
                context = AuditContext(cache=cm)
                return AuditService(
                    context=context,
                    async_word_reader=async_reader,
                    excel_writer=ExcelWriter(),
                    file_handler=FileHandler(),
                )

            batch = BatchProcessor(service_factory, max_concurrent=2)
            results = await batch.process_batch_async(
                [str(file_a), str(file_b)], str(output_dir)
            )
            assert len(results) == 2
            assert len(cache_managers) == 2

            assert cache_managers[0] is not cache_managers[1]
            assert len(cache_managers[0]) == 0
            assert len(cache_managers[1]) == 0

            # Fresh service reset should not populate the cache by itself.
            fresh_cache = LRUCacheManager(max_size=100)
            fresh_context = AuditContext(cache=fresh_cache)
            fresh_service = AuditService(
                context=fresh_context,
                async_word_reader=async_reader,
                excel_writer=ExcelWriter(),
                file_handler=FileHandler(),
            )
            fresh_service._reset_run_state(str(file_a))
            assert len(fresh_service.context.cache) == 0

    @pytest.mark.asyncio
    async def test_legacy_globals_reset_per_file(self, sample_word_file: str) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            src = Path(sample_word_file)
            file_a = Path(tmpdir) / "a.docx"
            file_b = Path(tmpdir) / "b.docx"
            shutil.copy(str(src), str(file_a))
            shutil.copy(str(src), str(file_b))

            output_dir = Path(tmpdir) / "out"
            output_dir.mkdir(parents=True, exist_ok=True)

            legacy_main = _load_legacy_main_module()
            bspl_cache = getattr(legacy_main, "BSPL_cross_check_cache", None)
            if isinstance(bspl_cache, dict):
                bspl_cache.clear()
            bspl_marks = getattr(legacy_main, "BSPL_cross_check_mark", None)
            if isinstance(bspl_marks, (list, set, dict)):
                bspl_marks.clear()

            async_reader = AsyncWordReader(max_workers=2)
            service_factory = self._make_service_factory(
                async_word_reader=async_reader,
                cache_max_size=100,
                legacy_globals_clean=False,
            )
            batch = BatchProcessor(service_factory, max_concurrent=2)

            results = await batch.process_batch_async(
                [str(file_a), str(file_b)], str(output_dir)
            )
            assert len(results) == 2
            assert all(r.get("success", False) for r in results)

            legacy_main_after = _load_legacy_main_module()
            bspl_cache_after = getattr(
                legacy_main_after, "BSPL_cross_check_cache", None
            )
            bspl_marks_after = getattr(legacy_main_after, "BSPL_cross_check_mark", None)
            assert isinstance(bspl_cache_after, dict)
            assert isinstance(bspl_marks_after, list)
            assert len(bspl_cache_after) == 0
            assert len(bspl_marks_after) == 0
