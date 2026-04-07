"""
Phase 8: Integration test for full audit workflow and traceability.

Verifies:
- Full pipeline runs (Word -> validation -> Excel)
- run_id is set on run telemetry
- At least one table has extractor_engine (traceability)
"""

import json
from pathlib import Path

import pytest

from quality_audit.core.cache_manager import AuditContext, LRUCacheManager
from quality_audit.services.audit_service import AuditService


@pytest.fixture
def audit_service():
    """Create AuditService with default dependencies (shared by workflow and golden tests)."""
    context = AuditContext(cache=LRUCacheManager(max_size=1000))
    return AuditService(context=context)


class TestAuditWorkflowTraceability:
    """Integration tests for audit workflow and Phase 6 traceability."""

    def test_full_audit_workflow_sets_run_id_and_extractor_engine(
        self, audit_service, sample_word_file, tmp_path
    ):
        """
        Run full audit and assert traceability: run_id and extractor_engine.
        """
        excel_path = tmp_path / "traceability_test.xlsx"
        result = audit_service.audit_document(sample_word_file, str(excel_path))

        assert result["success"] is True, result.get("error", "unknown")
        assert result["tables_processed"] > 0
        assert excel_path.exists()

        run_tel = audit_service.telemetry.run_telemetry
        assert run_tel.run_id, "run_id must be set after run (Phase 6 traceability)"
        assert len(run_tel.tables) >= 1
        extractor_engines = [
            t.extractor_engine for t in run_tel.tables if t.extractor_engine
        ]
        assert (
            extractor_engines
        ), "At least one table must have extractor_engine set (Phase 6 traceability)"

    def test_telemetry_to_dict_includes_run_id_and_extractor_engine(
        self, audit_service, sample_word_file, tmp_path
    ):
        """Telemetry serialization includes run_id and per-table extractor_engine."""
        excel_path = tmp_path / "telemetry_dict_test.xlsx"
        audit_service.audit_document(sample_word_file, str(excel_path))

        d = audit_service.telemetry.run_telemetry.to_dict()
        assert d["run_id"], "to_dict() must include non-empty run_id"
        assert d["tables"]
        with_engine = [t for t in d["tables"] if t.get("extractor_engine")]
        assert with_engine, "At least one table in to_dict() must have extractor_engine"


class TestGoldenRegression:
    """Regression tests using golden fs2018_golden_results.json."""

    @pytest.fixture
    def golden_path(self):
        """Path to golden acceptance file."""
        return (
            Path(__file__).resolve().parent.parent
            / "fixtures"
            / "fs2018_golden_results.json"
        )

    def test_golden_file_exists_and_valid(self, golden_path):
        """Golden fixture exists and has expected structure."""
        assert golden_path.exists(), f"Golden file missing: {golden_path}"
        with open(golden_path, encoding="utf-8") as f:
            golden = json.load(f)
        assert "version" in golden
        assert "acceptance" in golden
        assert golden["acceptance"].get("warn_ratio_max") is not None
        assert golden["acceptance"].get("totals_recall_min") is not None
        assert golden.get("traceability", {}).get("run_id_required") is True
        assert golden.get("traceability", {}).get("extractor_engine_required") is True

    def test_warn_ratio_below_golden_threshold(
        self, audit_service, sample_word_file, golden_path, tmp_path
    ):
        """
        Phase 6.2: After full audit, WARN ratio (tables with status_enum WARN / total tables)
        must be <= golden acceptance warn_ratio_max (e.g. 3%).
        """
        with open(golden_path, encoding="utf-8") as f:
            golden = json.load(f)
        warn_ratio_max = golden["acceptance"]["warn_ratio_max"]

        excel_path = tmp_path / "warn_ratio_test.xlsx"
        result = audit_service.audit_document(sample_word_file, str(excel_path))

        assert result["success"] is True, result.get("error", "unknown")
        results = result.get("results", [])
        total = len(results)
        assert total > 0, "Need at least one table to compute WARN ratio"

        warn_count = sum(1 for r in results if r.get("status_enum") == "WARN")
        warn_ratio = warn_count / total
        assert warn_ratio <= warn_ratio_max, (
            f"WARN ratio {warn_ratio:.2%} (warn_count={warn_count}, total={total}) "
            f"exceeds golden warn_ratio_max={warn_ratio_max:.2%}"
        )
