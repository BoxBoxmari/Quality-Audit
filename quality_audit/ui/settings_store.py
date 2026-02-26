"""Simple JSON settings storage for GUI preferences."""

import json
from pathlib import Path
from typing import Any, Dict, cast


def load_settings(tool_root: Path) -> Dict[str, Any]:
    """Load settings from .quality_audit_gui.json"""
    settings_path = tool_root / ".quality_audit_gui.json"
    if settings_path.exists():
        try:
            with open(settings_path, encoding="utf-8") as f:
                return cast(Dict[str, Any], json.load(f))
        except Exception:
            return {}
    return {}


def save_settings(tool_root: Path, settings: Dict[str, Any]) -> None:
    """Atomically save settings to .quality_audit_gui.json"""
    settings_path = tool_root / ".quality_audit_gui.json"
    temp_path = settings_path.with_suffix(".json.tmp")
    try:
        with open(temp_path, "w", encoding="utf-8") as f:
            json.dump(settings, f, indent=2)
        temp_path.replace(settings_path)
    except Exception:
        if temp_path.exists():
            temp_path.unlink()
