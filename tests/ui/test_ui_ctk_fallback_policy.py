import pytest

import quality_audit.ui_ctk.app as ctk_app


def test_ctk_no_silent_fallback_when_disabled(monkeypatch):
    monkeypatch.setattr(
        ctk_app, "get_feature_flags", lambda: {"ui_ctk_allow_legacy_fallback": False}
    )
    monkeypatch.setattr(
        "quality_audit.ui_ctk.main_window.launch_ctk",
        lambda: (_ for _ in ()).throw(RuntimeError("boom")),
    )

    with pytest.raises(RuntimeError):
        ctk_app.run()


def test_ctk_explicit_legacy_fallback_when_enabled(monkeypatch):
    called = {"legacy": False}

    monkeypatch.setattr(
        ctk_app, "get_feature_flags", lambda: {"ui_ctk_allow_legacy_fallback": True}
    )
    monkeypatch.setattr(
        "quality_audit.ui_ctk.main_window.launch_ctk",
        lambda: (_ for _ in ()).throw(RuntimeError("boom")),
    )

    class _LegacyGUI:
        def mainloop(self):
            called["legacy"] = True

    monkeypatch.setattr("quality_audit.ui.tk_cli_gui.QualityAuditGUI", _LegacyGUI)
    ctk_app.run()
    assert called["legacy"] is True
