# Kept Enhancements Register

Track non-destructive enhancements retained outside authoritative baseline decisions.

| Area | File(s) | Classification | Default-path role | Why kept |
|---|---|---|---|---|
| Multi-engine extraction orchestration | `quality_audit/io/word_reader.py` | KEEP_AS_IS | Input robustness only | Improves table capture without changing audit rule ownership. |
| OOXML / python-docx / render-first / html fallback stack | `quality_audit/io/extractors/*` | KEEP_AS_IS | Input robustness only | Deterministic, capability-gated fallback increases resilience. |
| Canonicalization and column-role helpers | `quality_audit/utils/table_normalizer.py`, `quality_audit/utils/column_roles.py`, `quality_audit/utils/table_canonicalizer.py` | KEEP_AS_IS | Pre-validation normalization | Reduces parser noise and stabilizes DTO handoff. |
| CTK UI shell | `quality_audit/ui_ctk/*` | KEEP_AS_IS | UI shell only | Replaces Tk default path; backend boundaries unchanged. |
| Legacy-compat fallback UI | `quality_audit/ui/tk_cli_gui.py` | KEEP_BUT_MOVE_OUT_OF_DEFAULT_AUDIT_PATH | Disabled by default | Needed for explicit compatibility mode only. |
| Parity/shadow controls | `quality_audit/config/feature_flags.py` | KEEP_BUT_MOVE_OUT_OF_DEFAULT_AUDIT_PATH | Explicit opt-in only | Allows diagnostics/experiments without default semantic takeover. |
