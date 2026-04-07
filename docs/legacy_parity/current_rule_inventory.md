# Current Rule Inventory

## Default Runtime Contract
`AuditService -> extraction/normalization -> legacy_audit.router -> legacy_audit.engine -> Excel writer`

## Decision Ownership
| Block | Owner | Bucket | Notes |
|---|---|---|---|
| Baseline routing | `core/legacy_audit/router.py` | MERGE_INTO_BASELINE | Heading/catalog first, metadata as hint only. |
| Baseline decision engine | `core/legacy_audit/engine.py` | MERGE_INTO_BASELINE | Default authoritative decision path. |
| Catalogs/codes | `core/legacy_audit/catalogs.py`, `codes.py` | MERGE_INTO_BASELINE | Union restored; compatibility re-exports stay in config. |
| Legacy heading aliases | `core/legacy_audit/headings.py` | MERGE_INTO_BASELINE | Simple baseline-compatible routing fallback. |
| Validator factory/hybrid logic | `core/validators/factory.py` | KEEP_BUT_MOVE_OUT_OF_DEFAULT_AUDIT_PATH | Compatibility path only for non-baseline flows/tests. |
| Generic evidence/movement heuristics | `core/validators/*` | KEEP_BUT_MOVE_OUT_OF_DEFAULT_AUDIT_PATH | Off by default via feature flags. |
| Extraction metadata | `io/word_reader.py`, normalization utils | KEEP_AS_IS | Non-authoritative metadata/support role. |
| CTK UI | `ui_ctk/*` | KEEP_AS_IS | Real default UI; no silent Tk fallback. |
| Tk UI | `ui/tk_cli_gui.py` | KEEP_BUT_MOVE_OUT_OF_DEFAULT_AUDIT_PATH | Explicit compatibility path only. |

## Default Boundary Flags (strict)
- `baseline_authoritative_default=True`
- `ui_ctk_allow_legacy_fallback=False`
- `nonbaseline_code_pattern_routing_fallback=False` (forced when baseline mode is on)
- Decision-shaping modern heuristics default OFF unless explicitly enabled with `nonbaseline_*`, `experimental_*`, or `legacy_parity_shadow_*` prefixes.
