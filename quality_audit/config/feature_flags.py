"""
Feature flags for Quality Audit tool.
Used for safe rollout and backward compatibility of routing/validator changes.
"""

FEATURE_FLAGS = {
    "heading_fallback_from_table_first_row": True,
    "classifier_scan_expansion": True,
    "skip_footer_signature_tables": True,
    "generic_exclude_code_columns": True,
    "multi_code_columns_exclusion": True,  # Exclude all Code/Code.1/Code.2... from sums
    "code_column_value_heuristic": False,  # Optional: detect code by cell value distribution; keep off
    "strict_netting_structure": True,
    # Enable document-level cash flow cross-table context by default to reduce false FAILs
    # when cash flow information is split across multiple tables. Tests can still override
    # this flag via monkeypatch where needed.
    "cashflow_cross_table_context": True,
    # Pattern C diagnostics: debug log when sum_detail=0 and total_on_table>0.
    # Set False to reduce log volume in production after rollout.
    "enable_pattern_c_diagnostics": True,
    # Epic 557409ef: Extract/Normalization/Validator safety
    # B1: Deduplicate/coalesce duplicated period columns before validation.
    "dedup_period_columns": True,
    # B2: Robust numeric parsing (NBSP, em-dash, mixed separators, trailing units).
    "robust_numeric_parsing": True,
    # A1: Safer total row selection (hybrid + safe fallback).
    "safe_total_row_selection": True,
    # Canonicalize DOCX output: shared canonicalizer for writer and validators.
    # Rollout order: validator ON -> writer ON -> merge_aware_extraction ON.
    "enable_canonicalize_validator": True,
    "enable_canonicalize_writer": False,
    "enable_merge_aware_extraction": False,
    # Quality gap: heading inference v2 (junk filter, proximity, section boundary)
    "heading_inference_v2": True,
    # Phase 2: Classifier content override when heading weak; TAX_NOTE only with content evidence
    "classifier_content_override": True,
    "tax_routing_content_evidence": True,
    # Phase 3: Extractor usable v2 (period-like duplicate only, caption, header row, multi-signal unusable)
    "extractor_usable_v2": True,
    # Phase 4: Generic validator evidence gate and movement roll-forward
    "generic_evidence_gate": True,
    "movement_rollforward": True,
    # False FAIL reduction: eligibility gate before COLUMN_TOTAL_VALIDATION (detail count + total keyword)
    "enable_generic_total_gate": True,
    # Tighten total row selection: prefer keyword-based; avoid line items (profit/income without "total")
    "tighten_total_row_keywords": False,
    # Phase 4 A2: When True, keep PASS when assertions_count=0 (no override to INFO_SKIPPED)
    "treat_no_assertion_as_pass": False,
    # Phase 5: EquityValidator dynamic header and multi-row header
    "equity_header_infer": True,
    # Phase 5 B1: When expected=0 (no numeric evidence in slice) and actual!=0, treat as NO_EVIDENCE (INFO) not FAIL
    "equity_no_evidence_not_fail": True,
    # Footer/signature artifacts: exclude from output and KPI denominator
    "metrics_exclude_footer_signature_artifacts": True,
    # BalanceSheet routing: gate on numeric evidence to avoid NO_NUMERIC_EVIDENCE false failures
    "routing_balance_sheet_gating_enabled": True,
    "routing_balance_sheet_gating_policy": "downgrade_to_generic",  # or "skip_no_numeric"
    "routing_balance_sheet_numeric_threshold": 0.25,
    # Netting structure adjacency: strict (rows) and relaxed (rows) for Total/Less/Net detection
    "netting_adjacency_strict": 5,
    "netting_adjacency_relaxed": 25,
    # Group 1/3/4: when no chosen_numeric, treat last two columns as NUMERIC if density > 0.1 (reduce NO_NUMERIC_EVIDENCE)
    "use_last_two_columns_fallback": False,
    # Extraction fallback: prefer render-first before python-docx when signals indicate difficulty
    "extraction_fallback_prefer_advanced_before_legacy": True,
    "extraction_render_first_triggered_mode": "signals_only",  # or "always_off", "always_on"
}


def get_feature_flags():
    """Return current feature flags dict (copy)."""
    return dict(FEATURE_FLAGS)
