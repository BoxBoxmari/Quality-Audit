from __future__ import annotations

from pathlib import Path

import pytest

from quality_audit.ui_ctk import runtime_contract as rc


def _spec(
    *,
    source_type: rc.InputSourceType = "folder",
    input_path: Path | None = None,
    discovered: tuple[Path, ...] = (),
    base_path: Path | None = None,
    tax_mode: rc.TaxMode = "all",
    all_rate: float | None = None,
    default_rate: float | None = None,
    per_file: dict[str, float] | None = None,
    output_dir: Path | None = None,
) -> rc.RunSpec:
    return rc.RunSpec(
        input_source_type=source_type,
        input_source_path=input_path,
        selected_files=(),
        discovered_files=discovered,
        base_path=base_path,
        output_dir=output_dir or Path.cwd(),
        tax_mode=tax_mode,
        all_rate_percent=all_rate,
        default_rate_percent=default_rate,
        per_file_rates_percent=per_file or {},
    )


def test_discover_docx_for_folder_file_and_multi(tmp_path: Path):
    folder = tmp_path / "in"
    folder.mkdir()
    keep = folder / "a.docx"
    keep.write_text("x", encoding="utf-8")
    skip = folder / "~$temp.docx"
    skip.write_text("x", encoding="utf-8")
    nested = folder / "x" / "b.docx"
    nested.parent.mkdir()
    nested.write_text("x", encoding="utf-8")

    found_folder, base_folder = rc.discover_docx("folder", folder, [])
    assert [p.name for p in found_folder] == ["a.docx", "b.docx"]
    assert base_folder == folder.resolve()

    found_file, base_file = rc.discover_docx("file", keep, [])
    assert found_file == [keep.resolve()]
    assert base_file == keep.resolve().parent

    found_multi, base_multi = rc.discover_docx(
        "multi_files",
        None,
        [keep, nested],
    )
    assert found_multi == [keep.resolve(), nested.resolve()]
    assert base_multi is None


def test_build_tax_config_modes(tmp_path: Path):
    p = (tmp_path / "a.docx").resolve()
    p.write_text("x", encoding="utf-8")

    all_cfg = rc.build_tax_config(
        _spec(tax_mode="all", all_rate=20.0, discovered=(p,), base_path=tmp_path)
    )
    assert all_cfg.mode == "all"
    assert all_cfg.all_rate == 0.2

    indiv_cfg = rc.build_tax_config(
        _spec(
            tax_mode="individual",
            default_rate=25.0,
            per_file={p.name: 18.0},
            discovered=(p,),
            base_path=tmp_path,
        )
    )
    assert indiv_cfg.mode == "individual"
    assert indiv_cfg.map_data is not None
    assert indiv_cfg.map_data["default"] == 0.25
    assert indiv_cfg.map_data[p.name] == 0.18

    with pytest.raises(ValueError, match="Unsupported tax mode"):
        rc.build_tax_config(_spec(tax_mode="unsupported"))  # type: ignore[arg-type]


def test_build_cli_argv_for_folder_all_mode(tmp_path: Path):
    spec = _spec(
        source_type="folder",
        input_path=tmp_path,
        tax_mode="all",
        all_rate=15.0,
        output_dir=tmp_path / "out",
    )
    argv = rc.build_cli_argv(spec)
    assert argv[0] == str(tmp_path)
    assert "--output-dir" in argv
    assert "--tax-rate-mode" in argv
    assert "--tax-rate" in argv
    assert "15.0" in argv


def test_run_spec_folder_uses_cli_contract(tmp_path: Path, monkeypatch):
    calls: list[list[str]] = []

    def _fake_cli(argv):
        calls.append(list(argv))
        return 0

    monkeypatch.setattr(rc, "cli_main", _fake_cli)
    src = tmp_path / "input"
    src.mkdir()
    spec = _spec(
        source_type="folder",
        input_path=src,
        tax_mode="all",
        all_rate=12.0,
        output_dir=tmp_path / "out",
    )
    exit_code = rc.run_spec(spec, lambda _msg: None)
    assert exit_code == 0
    assert len(calls) == 1
    assert calls[0][0] == str(src)


def test_run_spec_multi_files_does_not_call_cli_main(tmp_path: Path, monkeypatch):
    called_cli = False

    def _fake_cli(_argv):
        nonlocal called_cli
        called_cli = True
        return 1

    class _FakeBatch:
        def __init__(self, *_args, **_kwargs):
            pass

        async def process_batch_async(
            self,
            file_paths,
            output_dir,
            output_suffix="_output.xlsx",
            on_file_complete=None,
        ):
            results = [
                {"success": True, "input_file": p, "tables_processed": 1}
                for p in file_paths
            ]
            if on_file_complete:
                for r in results:
                    on_file_complete(r)
            return results

    monkeypatch.setattr(rc, "cli_main", _fake_cli)
    monkeypatch.setattr(rc, "BatchProcessor", _FakeBatch)

    f = (tmp_path / "x.docx").resolve()
    f.write_text("x", encoding="utf-8")
    spec = _spec(
        source_type="multi_files",
        discovered=(f,),
        base_path=tmp_path,
        tax_mode="all",
        all_rate=25.0,
        output_dir=tmp_path / "out",
    )
    exit_code = rc.run_spec(spec, lambda _msg: None)
    assert exit_code == 0
    assert called_cli is False


def test_run_spec_multi_files_emits_progress(tmp_path: Path, monkeypatch):
    emitted = []

    class _FakeBatch:
        def __init__(self, *_args, **_kwargs):
            pass

        async def process_batch_async(
            self,
            file_paths,
            output_dir,
            output_suffix="_output.xlsx",
            on_file_complete=None,
        ):
            results = []
            for p in file_paths:
                item = {"success": True, "input_file": p, "tables_processed": 1}
                results.append(item)
                if on_file_complete:
                    on_file_complete(item)
            return results

    monkeypatch.setattr(rc, "BatchProcessor", _FakeBatch)
    f1 = (tmp_path / "a.docx").resolve()
    f2 = (tmp_path / "b.docx").resolve()
    f1.write_text("x", encoding="utf-8")
    f2.write_text("x", encoding="utf-8")
    spec = _spec(
        source_type="multi_files",
        discovered=(f1, f2),
        base_path=tmp_path,
        tax_mode="all",
        all_rate=25.0,
        output_dir=tmp_path / "out",
    )
    exit_code = rc.run_spec(
        spec, lambda _msg: None, progress=lambda p: emitted.append(p)
    )
    assert exit_code == 0
    assert len(emitted) == 2
    assert emitted[-1]["processed"] == 2
    assert emitted[-1]["total"] == 2
