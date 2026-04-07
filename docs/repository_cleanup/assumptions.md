# Cleanup Assumptions

- `main.py` remains a supported CLI wrapper and must stay at repository root.
- `openmemory.md` is retained because it is referenced by existing architecture/audit docs.
- Root-level `TASK.md` is treated as deprecated duplicate of `docs/TASK.md` and archived.
- `quality_audit.zip` is treated as historical/export artifact, not active runtime input.
- `quality_audit_legacy_parity_report.docx` is retained as evidence but relocated to parity evidence folder.
- Cache and bytecode artifacts are reproducible and safe to remove.
