# UI Migration Plan

- Default UI entrypoint is `quality_audit/ui_ctk` (CTK shell).
- Launch path:
  - `python -m quality_audit.ui_ctk`
  - `run_gui.bat` -> `pythonw -m quality_audit.ui_ctk`
- Backend boundary unchanged:
  - UI orchestrates file picks and run actions only.
  - Audit logic remains in `AuditService` and core validators.
- Tk compatibility path:
  - `quality_audit/ui/tk_cli_gui.py` is retained only for explicit compatibility fallback.
  - No silent fallback in default path (`ui_ctk_allow_legacy_fallback=False` by default).
- Safety checks:
  - UI tests assert CTK default modules do not import Tk directly.
  - Fallback policy tests assert legacy Tk path is explicit, not implicit.
