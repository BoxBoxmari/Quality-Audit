# Removal Candidates

| Candidate | Bucket | Action |
|---|---|---|
| Modern hybrid validator routing as default authority | REPLACE_WITH_LEGACY | keep factory for compatibility only; default service uses legacy engine |
| Decision-shaping heuristics on default path (`cashflow_cross_table_context`, `generic_evidence_gate`, `movement_rollforward`, `note_structure_engine` gating) | KEEP_BUT_MOVE_OUT_OF_DEFAULT_AUDIT_PATH | keep behind explicit nonbaseline flags |
| Silent CTK -> Tk fallback | REMOVE | disallow by default; explicit compatibility flag only |
| Any runtime import from `legacy/*.py` path | REMOVE | prohibit; use ported `core/legacy_audit/*` modules only |
