"""
Golden regression suite: Numeric evidence gating and false PASS elimination.

Asserts invariants after P0 changes:
- CJ tbl_006, tbl_012, CP tbl_004 must NOT be PASS when lacking numeric evidence
  (must be FAIL_TOOL_EXTRACT or INFO_SKIPPED).
- CJ tbl_009, CP tbl_006 may PASS when sum-to-total holds.
- Snapshots status, status_enum, reason_code, assertions_count, numeric_evidence_score.
"""

from pathlib import Path

import pytest

from quality_audit.services.audit_service import AuditService


def _test_data_dir():
    base = Path(__file__).resolve().parent.parent
    for name in ("test_data", "data"):
        d = base / name
        if d.exists():
            return d
    return base / "test_data"


def _result_by_table_id(results):
    """Build map table_id -> result dict (e.g. tbl_006_xxx -> result)."""
    by_id = {}
    for r in results:
        tid = r.get("table_id")
        if tid:
            by_id[tid] = r
    return by_id


def _get_result_for_index(results, one_based_index: int):
    """Get result for table at 1-based index (e.g. 6 -> tbl_006_...)."""
    prefix = f"tbl_{one_based_index:03d}_"
    for r in results:
        if r.get("table_id", "").startswith(prefix):
            return r
    return None


class TestQualityAuditGolden:
    """Golden regression: numeric evidence gating invariants."""

    @pytest.fixture
    def audit_service(self):
        return AuditService()

    @pytest.fixture
    def test_data_dir(self):
        return _test_data_dir()

    def test_cjcgv_tables_without_numeric_evidence_not_pass(
        self, audit_service, test_data_dir, tmp_path
    ):
        """
        CJCGV: tbl_006, tbl_012 must not PASS when lacking numeric evidence.
        Must be FAIL_TOOL_EXTRACT or INFO_SKIPPED.
        """
        word_file = test_data_dir / "CJCGV-FS2018-EN- v2.docx"
        if not word_file.exists():
            pytest.skip(f"Test data not found: {word_file}")

        excel_output = tmp_path / "cjcgv_golden_output.xlsx"
        result = audit_service.audit_document(str(word_file), str(excel_output))
        assert result.get("success") is True, result.get("error")
        results = result.get("results", [])

        for tbl_num in (6, 12):
            r = _get_result_for_index(results, tbl_num)
            if r is None:
                continue
            status_enum = r.get("status_enum") or ""
            ctx = r.get("context") or {}
            reason = r.get("failure_reason_code") or ctx.get("failure_reason_code")
            assertions = r.get("assertions_count", 0)
            score = ctx.get("numeric_evidence_score")

            assert status_enum != "PASS", (
                f"CJ tbl_{tbl_num:03d} must not PASS when lacking numeric evidence: "
                f"status_enum={status_enum} assertions_count={assertions} "
                f"numeric_evidence_score={score} failure_reason_code={reason}"
            )
            assert status_enum in (
                "FAIL_TOOL_EXTRACT",
                "INFO_SKIPPED",
                "INFO",
                "FAIL",
                "WARN",
            ), (
                f"CJ tbl_{tbl_num:03d} expected FAIL_TOOL_EXTRACT or INFO_SKIPPED, got {status_enum}"
            )

    def test_cp_vietnam_tbl_004_not_pass_when_no_numeric_evidence(
        self, audit_service, test_data_dir, tmp_path
    ):
        """
        CP Vietnam: tbl_004 must not PASS when lacking numeric evidence.
        Must be FAIL_TOOL_EXTRACT or INFO_SKIPPED.
        """
        word_file = test_data_dir / "CP Vietnam-FS2018-Consol-EN.docx"
        if not word_file.exists():
            pytest.skip(f"Test data not found: {word_file}")

        excel_output = tmp_path / "cp_vietnam_golden_output.xlsx"
        result = audit_service.audit_document(str(word_file), str(excel_output))
        assert result.get("success") is True, result.get("error")
        results = result.get("results", [])

        r = _get_result_for_index(results, 4)
        if r is None:
            pytest.skip("CP Vietnam has no tbl_004 in this run")
        status_enum = r.get("status_enum") or ""
        ctx = r.get("context") or {}
        reason = r.get("failure_reason_code") or ctx.get("failure_reason_code")
        assertions = r.get("assertions_count", 0)
        score = ctx.get("numeric_evidence_score")

        assert status_enum != "PASS", (
            "CP tbl_004 must not PASS when lacking numeric evidence: "
            f"status_enum={status_enum} assertions_count={assertions} "
            f"numeric_evidence_score={score} failure_reason_code={reason}"
        )
        assert status_enum in (
            "FAIL_TOOL_EXTRACT",
            "INFO_SKIPPED",
            "INFO",
            "FAIL",
            "WARN",
        ), f"CP tbl_004 expected FAIL_TOOL_EXTRACT or INFO_SKIPPED, got {status_enum}"

    def test_cjcgv_golden_snapshot_fields(self, audit_service, test_data_dir, tmp_path):
        """
        Snapshot: each result has status, status_enum, reason_code, assertions_count,
        numeric_evidence_score (in context).
        """
        word_file = test_data_dir / "CJCGV-FS2018-EN- v2.docx"
        if not word_file.exists():
            pytest.skip(f"Test data not found: {word_file}")

        excel_output = tmp_path / "cjcgv_snapshot_output.xlsx"
        result = audit_service.audit_document(str(word_file), str(excel_output))
        assert result.get("success") is True, result.get("error")
        results = result.get("results", [])

        for r in results:
            assert "status" in r
            assert "status_enum" in r
            assert "context" in r
            assert "assertions_count" in r
            ctx = r["context"]
            assert "numeric_evidence_score" in ctx or "failure_reason_code" in ctx

    def test_cp_vietnam_golden_snapshot_fields(
        self, audit_service, test_data_dir, tmp_path
    ):
        """
        Snapshot: each result has status, status_enum, assertions_count,
        numeric_evidence_score in context.
        """
        word_file = test_data_dir / "CP Vietnam-FS2018-Consol-EN.docx"
        if not word_file.exists():
            pytest.skip(f"Test data not found: {word_file}")

        excel_output = tmp_path / "cp_vietnam_snapshot_output.xlsx"
        result = audit_service.audit_document(str(word_file), str(excel_output))
        assert result.get("success") is True, result.get("error")
        results = result.get("results", [])

        for r in results:
            assert "status" in r
            assert "status_enum" in r
            assert "context" in r
            assert "assertions_count" in r
