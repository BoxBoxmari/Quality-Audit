from __future__ import annotations

from pathlib import Path
from typing import Any, List, Optional


def ask_open_docx_paths(parent: Optional[Any] = None) -> List[str]:
    """Open native multi-select file dialog tied to the Tk/CTk event loop.

    PowerShell + subprocess blocked the UI thread while the dialog was open,
    which made Windows report the app as Not Responding.
    """
    from tkinter import filedialog

    paths = filedialog.askopenfilenames(
        parent=parent,
        title="Select DOCX Files",
        filetypes=[("DOCX Files", "*.docx"), ("All Files", "*.*")],
    )
    if not paths:
        return []
    return [str(Path(p).resolve()) for p in paths]


def ask_open_docx_file(parent: Optional[Any] = None) -> Optional[str]:
    """Open single DOCX file dialog and return absolute path."""
    from tkinter import filedialog

    path = filedialog.askopenfilename(
        parent=parent,
        title="Select DOCX File",
        filetypes=[("DOCX Files", "*.docx"), ("All Files", "*.*")],
    )
    if not path:
        return None
    return str(Path(path).resolve())


def ask_open_docx_folder(parent: Optional[Any] = None) -> Optional[str]:
    """Open folder dialog for DOCX discovery."""
    from tkinter import filedialog

    path = filedialog.askdirectory(parent=parent, title="Select Input Folder")
    if not path:
        return None
    return str(Path(path).resolve())


def ask_output_directory(
    initial_dir: Optional[str] = None, parent: Optional[Any] = None
) -> Optional[str]:
    from tkinter import filedialog

    start_path = str(Path(initial_dir).resolve()) if initial_dir else str(Path.cwd())
    output = filedialog.askdirectory(
        parent=parent,
        title="Select Output Folder",
        initialdir=start_path,
    )
    if not output:
        return None
    return str(Path(output).resolve())
