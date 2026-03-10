# Feature Flags

Feature flags are defined in `quality_audit/config/feature_flags.py` (dict `FEATURE_FLAGS`, function `get_feature_flags()`). They control safe rollout and backward compatibility of routing/validator behaviour.

## False FAIL / INFO reduction

| Flag | Default | Description |
|------|---------|-------------|
| `treat_no_assertion_as_pass` | `False` | When `True`, tables with `assertions_count == 0` keep PASS instead of being overridden to INFO_SKIPPED with `failure_reason_code="NO_ASSERTIONS"`. Used to reduce false INFO for tables that pass eligibility but run no numeric checks. |
| `equity_no_evidence_not_fail` | `False` | When `True`, EquityValidator treats “expected=0 (no numeric evidence in slice), actual≠0” as NO_EVIDENCE (INFO, `ok=True`) instead of FAIL. Reduces false FAIL when equity slice has no numbers. |

## Netting structure adjacency

| Flag | Default | Description |
|------|---------|-------------|
| `netting_adjacency_strict` | `5` | Max row distance (strict) for Total/Less/Net netting structure detection. |
| `netting_adjacency_relaxed` | `25` | Max row distance (relaxed) for netting structure when strict fails. |

Used in `GenericTableValidator._detect_netting_structure()` to avoid missing structures when Total/Less/Net rows are more than 15 rows apart.

## NOTE structure engine

| Flag | Default | Description |
|------|---------|-------------|
| `note_structure_engine` | `True` | When `True`, NOTE tables (GENERIC_NOTE, TAX_NOTE, UNKNOWN numeric) use the NOTE structure analyzer (`analyze_note_table`) to detect label column, amount columns, row types, segments (OB/CB/movement), and scopes. Movement and scoped vertical sum rules then run with segment-aware logic. When `False`, the legacy path is used (last row as total, no segments). See `docs/NOTE_STRUCTURE_WARN_TAXONOMY.md` for WARN reason codes and manual review. |

## Other flags (summary)

- **Extraction / normalization:** `heading_fallback_from_table_first_row`, `classifier_scan_expansion`, `skip_footer_signature_tables`, `generic_exclude_code_columns`, `multi_code_columns_exclusion`, `code_column_value_heuristic`, `strict_netting_structure`, `dedup_period_columns`, `robust_numeric_parsing`, `safe_total_row_selection`, `enable_canonicalize_validator`, `enable_canonicalize_writer`, `enable_merge_aware_extraction`, `heading_inference_v2`, `classifier_content_override`, `tax_routing_content_evidence`, `extractor_usable_v2`, `extraction_fallback_prefer_advanced_before_legacy`, `extraction_render_first_triggered_mode`.
- **Validators / routing:** `cashflow_cross_table_context`, `enable_pattern_c_diagnostics`, `generic_evidence_gate`, `movement_rollforward`, `enable_generic_total_gate`, `tighten_total_row_keywords`, `equity_header_infer`, `routing_balance_sheet_gating_enabled`, `routing_balance_sheet_gating_policy`, `routing_balance_sheet_numeric_threshold`.
- **Metrics / output:** `metrics_exclude_footer_signature_artifacts`.

Full list and defaults: `quality_audit/config/feature_flags.py`.
