"""
Smoke E2E: run_regression_2docs pipeline.

When 2 default DOCX exist (tests/test_data or tests/data), runs full regression
and asserts report and outputs. Otherwise skips.
"""

import importlib.util
from pathlib import Path

import pytest

# Load script module without requiring scripts as package
_repo_root = Path(__file__).resolve().parents[2]
_script_path = _repo_root / "scripts" / "run_regression_2docs.py"
_spec = importlib.util.spec_from_file_location("run_regression_2docs", _script_path)
_run_regression_2docs = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(_run_regression_2docs)
run_regression = _run_regression_2docs.run_regression
_default_doc_paths = _run_regression_2docs._default_doc_paths


class TestRunRegression2DocsSmoke:
    """Smoke E2E for 2-DOCX regression pipeline."""

    def test_run_regression_2docs_when_default_docs_exist(self, tmp_path):
        """
        When CP Vietnam and CJCGV DOCX exist in tests/test_data or tests/data,
        run_regression() produces report and per-doc results.
        """
        doc_paths = _default_doc_paths()
        if len(doc_paths) < 2:
            pytest.skip(
                "Need 2 DOCX (e.g. CP Vietnam-FS2018-Consol-EN.docx, "
                "CJCGV-FS2018-EN- v2.docx) in tests/test_data or tests/data"
            )
        out = run_regression(
            doc_paths,
            tmp_path,
            run_aggregate=False,
            report_name="smoke_2docs.md",
            output_prefix="smoke",
        )
        assert "results" in out
        assert "report_path" in out
        report_path = Path(out["report_path"])
        assert report_path.exists(), f"Report not written: {report_path}"
        assert len(out["results"]) == 2
        # At least one doc should succeed if files exist
        successes = [r.get("success") for r in out["results"]]
        assert any(successes), f"Expected at least one success; got {out}"
