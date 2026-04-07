# Removed Logic Register

Track logic fully removed from default path (or deleted) with rationale and commit reference.

| Logic / behavior | File(s) | Classification | Current status | Rationale |
|---|---|---|---|---|
| Hybrid validator factory as default decision owner | `quality_audit/services/audit_service.py`, `quality_audit/core/validators/factory.py` | REPLACE_WITH_LEGACY | Removed from default path | Default now routes through `LegacyAuditEngine` in baseline mode. |
| Table-context statement-family forced routing in baseline mode | `quality_audit/services/audit_service.py` | REMOVE | Stripped before baseline validation | Prevents extraction metadata from overriding baseline route authority. |
| Silent CTK -> Tk fallback | `quality_audit/ui_ctk/app.py` | REMOVE | Disabled by default (explicit flag only) | Prevents hidden migration residue on default UI path. |
| Nonbaseline code-pattern routing drift in baseline mode | `quality_audit/config/feature_flags.py` | REMOVE | Force-disabled in baseline mode | Closes accidental semantic drift if flag is toggled. |
