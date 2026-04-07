# Baseline Authority Update (2026-03-23)

## Runtime ownership before/after
- Before: `AuditService` defaulted to legacy engine but router/engine compatibility branches still accepted nonbaseline hints/fallbacks.
- After: default decision ownership is strictly `legacy_audit.router -> legacy_audit.engine` without table-context family hints or generic compatibility reroute in legacy engine.

## Restored union items
- Expanded `TABLES_NEED_COLUMN_CHECK` to include remaining legacy-union items (acquisition/subsidiary, owners' equity changes, tax/state variants, deferred/provision/lease categories).
- Expanded `TABLES_NEED_CHECK_SEPARATELY` with legacy union entries (goodwill, investment-property variants, finance-lease tangible fixed assets, mature livestock).
- Expanded `TABLES_WITHOUT_TOTAL` with remaining legacy union entries (fair-value vs carrying, auditors' fees, geographical segments, interest rate risk, non-cash investing/financing activities).
- Added legacy union biological-assets items to `CROSS_CHECK_TABLES_FORM_2` and `CROSS_CHECK_TABLES_FORM_3`.

## Demoted/gated heuristics (default path)
- `cashflow_cross_table_context` forced off when `baseline_authoritative_default=True`.
- Default baseline path strips nonbaseline routing hints from table context (`statement_family`, `routing_reason`, continuity metadata) before legacy engine routing.
- Router no longer consumes `table_context` statement-family hints.
- `generic_evidence_gate`, `movement_rollforward`, `note_structure_engine`, `classifier_content_override`, `tax_routing_content_evidence` and related decision-shaping flags are forced off in baseline-authoritative mode.

## Extraction fallback policy
- `extraction_render_first_triggered_mode` default switched from `always_off` to `signals_only`.
- Active fallback chain now includes HTML export fallback before legacy reconstruction in `_extract_table_with_fallback`.
- Extraction backend remains non-authoritative for decision semantics; normalized table contract into legacy engine unchanged.

## UI boundary update
- Default CTK runtime modules no longer import `tkinter` directly.
- File/folder dialogs in CTK path moved to dedicated non-Tk adapter (`ui_ctk/file_dialogs.py`).
- Legacy Tk GUI remains explicit compatibility entrypoint only.

## Baseline script import statement
- Runtime does not import legacy scripts directly by file path; baseline constants/routing are consumed via `quality_audit/core/legacy_audit/*`.
