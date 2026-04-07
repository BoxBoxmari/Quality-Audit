"""Unit tests for default fixture resolution in run_regression_2docs."""

from pathlib import Path

import pytest

from scripts.run_regression_2docs import resolve_default_doc_paths


def test_resolve_prefers_data_under_root_first(tmp_path: Path) -> None:
    data = tmp_path / "data"
    data.mkdir()
    cp = data / "CP Vietnam-FS2018-Consol-EN.docx"
    cj = data / "CJCGV-FS2018-EN- v2 .DOCX"
    cp.write_bytes(b"fake")
    cj.write_bytes(b"fake")
    # Lower-priority folder also has pair — should not be used
    ttd = tmp_path / "tests" / "test_data"
    ttd.mkdir(parents=True)
    (ttd / "CP Vietnam-FS2018-Consol-EN.docx").write_bytes(b"other")
    (ttd / "CJCGV-FS2018-EN- v2.docx").write_bytes(b"other")

    out = resolve_default_doc_paths(tmp_path)
    assert len(out) == 2
    assert out[0] == cp.resolve()
    assert out[1] == cj.resolve()


def test_resolve_cjcgv_space_before_extension(tmp_path: Path) -> None:
    base = tmp_path / "tests" / "test_data"
    base.mkdir(parents=True)
    (base / "CP Vietnam-FS2018-Consol-EN.docx").write_bytes(b"a")
    (base / "CJCGV-FS2018-EN- v2 .docx").write_bytes(b"b")

    out = resolve_default_doc_paths(tmp_path)
    assert len(out) == 2
    assert out[1].name == "CJCGV-FS2018-EN- v2 .docx"


def test_resolve_empty_when_incomplete_pair(tmp_path: Path) -> None:
    data = tmp_path / "data"
    data.mkdir()
    (data / "CP Vietnam-FS2018-Consol-EN.docx").write_bytes(b"only")
    assert resolve_default_doc_paths(tmp_path) == []
