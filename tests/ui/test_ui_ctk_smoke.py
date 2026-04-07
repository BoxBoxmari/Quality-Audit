import importlib


def test_ui_ctk_module_importable():
    mod = importlib.import_module("quality_audit.ui_ctk.app")
    assert hasattr(mod, "run")
