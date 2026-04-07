from __future__ import annotations

import logging

from quality_audit.config.feature_flags import get_feature_flags

logger = logging.getLogger(__name__)


def run() -> None:
    try:
        from .main_window import launch_ctk

        launch_ctk()
    except ModuleNotFoundError as exc:
        if getattr(exc, "name", None) == "customtkinter":
            raise RuntimeError(
                "customtkinter is not installed. Install with: pip install 'customtkinter>=5.2.2' "
                "or pip install -r requirements.txt (use the same Python you run the app with)."
            ) from exc
        raise
    except Exception as exc:
        flags = get_feature_flags()
        if flags.get("ui_ctk_allow_legacy_fallback", False):
            logger.exception(
                "CustomTkinter UI failed; explicit compatibility fallback enabled"
            )
            from quality_audit.ui.tk_cli_gui import QualityAuditGUI

            QualityAuditGUI().mainloop()
            return
        logger.exception("CustomTkinter UI failed; legacy fallback disabled by default")
        raise RuntimeError(
            "CustomTkinter launch failed. Use explicit legacy compatibility entrypoint if needed."
        ) from exc
