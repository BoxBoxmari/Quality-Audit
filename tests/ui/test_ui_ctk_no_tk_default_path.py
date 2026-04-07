from pathlib import Path


def test_ctk_main_window_does_not_import_tkinter_directly():
    root = Path(__file__).resolve().parents[2]
    main_window_src = (root / "quality_audit" / "ui_ctk" / "main_window.py").read_text(
        encoding="utf-8"
    )
    assert "import tkinter" not in main_window_src
    assert "from tkinter" not in main_window_src


def test_file_dialogs_uses_tk_filedialog_for_docx_not_powershell_open():
    """DOCX picker must use askopenfilenames (Tk loop), not blocking subprocess dialog."""
    root = Path(__file__).resolve().parents[2]
    file_dialogs_src = (
        root / "quality_audit" / "ui_ctk" / "file_dialogs.py"
    ).read_text(encoding="utf-8")
    assert "askopenfilenames" in file_dialogs_src
    assert "OpenFileDialog" not in file_dialogs_src
