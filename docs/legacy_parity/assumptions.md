# Assumptions

- Regression oracle pair remains: `data/CP*` and `data/CJCGV*`.
- Existing extractor/normalization stack is retained for capture quality and diagnostics.
- Baseline authority for default PASS/WARN/FAIL is the ported legacy core under `quality_audit/core/legacy_audit/*`.
- Runtime does not import `legacy/main.py` or `legacy/Quality Audit.py` by path.
- Metadata fields (`note_model`, `header_semantics_summary`, `formula_profile`, extractor confidence/grouping fields) are diagnostics by default, not mandatory baseline gates.
- Compatibility wrappers remain allowed while non-authoritative by default path.
- `baseline_authoritative_default=True` is treated as production default contract.
- Under baseline mode, nonbaseline decision toggles are forcibly disabled (including `nonbaseline_code_pattern_routing_fallback`) even if statically set `True`.
