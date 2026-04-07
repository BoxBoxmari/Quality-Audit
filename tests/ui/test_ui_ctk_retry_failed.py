from __future__ import annotations

from pathlib import Path

from quality_audit.ui_ctk.main_window import CTKAuditApp


class _PathVar:
    def __init__(self) -> None:
        self.value = ""

    def set(self, value: str) -> None:
        self.value = value


def test_retry_failed_selects_failed_files_and_runs(tmp_path: Path) -> None:
    app = CTKAuditApp.__new__(CTKAuditApp)
    app._running = False
    app._failed_file_paths = [tmp_path / "a.docx", tmp_path / "b.docx"]
    app.selected_files = []
    app.input_source_path = tmp_path
    app.input_source_type = "folder"
    app.input_path_var = _PathVar()

    rescan_calls = 0
    run_calls = 0
    logs: list[str] = []

    def _rescan() -> None:
        nonlocal rescan_calls
        rescan_calls += 1

    def _run() -> None:
        nonlocal run_calls
        run_calls += 1

    def _log(msg: str) -> None:
        logs.append(msg)

    app._on_rescan = _rescan  # type: ignore[method-assign]
    app._on_run = _run  # type: ignore[method-assign]
    app._append_log = _log  # type: ignore[method-assign]

    app._on_retry_failed()

    assert app.input_source_type == "multi_files"
    assert app.input_source_path is None
    assert len(app.selected_files) == 2
    assert rescan_calls == 1
    assert run_calls == 1
    assert "Retry mode:" in logs[0]
    assert "(+1 more)" in app.input_path_var.value
