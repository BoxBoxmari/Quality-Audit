"""
Feature flags for Quality Audit tool.

Canonical single-path runtime note:
- Production correctness is owned by legacy/main.py via AuditService.
- Flags here are for shell behavior and experimental/non-runtime flows only.
"""

FEATURE_FLAGS = {
    # Legacy/reference controls:
    # - legacy_reference_mode: enable extra legacy diagnostics/tracing only.
    # - legacy_bug_compatibility_mode: opt-in runtime compatibility with known-buggy legacy paths.
    #   MUST stay off by default so corrected parity is the runtime default.
    "legacy_reference_mode": False,
    "legacy_bug_compatibility_mode": False,
    # Backward-compat alias. Keep key for older call-sites/tests, but default to corrected path.
    "legacy_parity_mode": False,
    "baseline_authoritative_default": False,
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
    "enable_canonicalize_writer": True,
    "enable_merge_aware_extraction": True,
    # Quality gap: heading inference v2 (junk filter, proximity, section boundary)
    "heading_inference_v2": True,
    # Phase 2: Classifier content override when heading weak; TAX_NOTE only with content evidence
    "classifier_content_override": True,
    "tax_routing_content_evidence": True,
    # Phase 3: Extractor usable v2 (period-like duplicate only, caption, header row, multi-signal unusable)
    "extractor_usable_v2": True,
    # Phase 4: Generic validator evidence gate and movement roll-forward
    "generic_evidence_gate": False,
    "movement_rollforward": True,
    # False FAIL reduction: eligibility gate before COLUMN_TOTAL_VALIDATION (detail count + total keyword)
    "enable_generic_total_gate": False,
    # Tighten total row selection: prefer keyword-based; avoid line items (profit/income without "total")
    "tighten_total_row_keywords": True,
    # Phase 4 A2: When True, keep PASS when assertions_count=0 (no override to INFO_SKIPPED)
    "treat_no_assertion_as_pass": False,
    # Phase 5: EquityValidator dynamic header and multi-row header
    "equity_header_infer": True,
    # Phase 5 B1: When expected=0 (no numeric evidence in slice) and actual!=0, treat as NO_EVIDENCE (INFO) not FAIL
    "equity_no_evidence_not_fail": False,
    # Footer/signature artifacts: exclude from output and KPI denominator
    "metrics_exclude_footer_signature_artifacts": True,
    # BalanceSheet routing: gate on numeric evidence to avoid NO_NUMERIC_EVIDENCE false failures
    "routing_balance_sheet_gating_enabled": False,
    "routing_balance_sheet_gating_policy": "downgrade_to_generic",  # or "skip_no_numeric"
    "routing_balance_sheet_numeric_threshold": 0.25,
    # Netting structure adjacency: strict (rows) and relaxed (rows) for Total/Less/Net detection
    "netting_adjacency_strict": 5,
    "netting_adjacency_relaxed": 25,
    # Group 1/3/4: when no chosen_numeric, treat last two columns as NUMERIC if density > 0.1 (reduce NO_NUMERIC_EVIDENCE)
    "use_last_two_columns_fallback": False,
    # Extraction fallback: prefer render-first before python-docx when signals indicate difficulty
    "extraction_fallback_prefer_advanced_before_legacy": True,
    "extraction_render_first_triggered_mode": "signals_only",
    # Feature flags for Tickets 6-10
    "ENABLE_SPLIT_TABLE_MERGE": True,
    "ENABLE_MATH_NETTING": True,
    "ENABLE_DENSITY_HEADER_PROMOTION": True,
    "ENABLE_DUAL_KEY_CROSS_CHECK": True,
    "ENABLE_NOTE_NUMBER_MAPPING": True,
    # Phase 2: Classification V2 (shadow mode — compare with V1, don't switch yet)
    "classification_v2_shadow": False,
    # Baseline-first shadow parity run: execute baseline + current in parallel and log diffs.
    "legacy_parity_shadow_mode": False,
    # Non-baseline diagnostics only; never authoritative in default path.
    "nonbaseline_note_model_gating": False,
    "nonbaseline_formula_profile_inference": False,
    "nonbaseline_present_code_composition": False,
    # Legacy router guard: code-pattern inference for family routing can drift
    # semantics on heading-indeterminate tables. Keep disabled by default.
    "nonbaseline_code_pattern_routing_fallback": False,
    # Experimental bucket
    "experimental_ui_ctk_shell": False,
    "ui_ctk_allow_legacy_fallback": False,
    # Phase 5: Big4 Audit Engine
    "enable_big4_engine": False,
    "enable_big4_shadow": False,
    # NOTE Structure Engine: analyze_note_table for NOTE tables; pass segments/scopes to rules
    "note_structure_engine": True,
    # When True, NOTE tables with undetermined structure get status WARN; otherwise INFO_SKIPPED
    "warn_on_structure_undetermined": False,
    # Patch 1: block merge across page break when headings mismatch
    "merge_block_heading_mismatch_on_page_break": True,
    # Patch 2: skip fallback total for tables in TABLES_WITHOUT_TOTAL
    "skip_fallback_total_for_no_total_tables": True,
    # Patch 3: exclude non-money header columns (year/rate/%) from amount_cols
    "amount_cols_header_filter": True,
    # Patch 4: exclude subtotal/netting rows from detail_rows
    "subtotal_exclusion_enabled": True,
}

# When legacy bug compatibility mode is effective, these must stay False regardless of
# static FEATURE_FLAGS or tests that monkeypatch the dict in place.
_PARITY_FORCED_FALSE_WHEN_LEGACY_PARITY = frozenset(
    {
        "enable_big4_engine",
        "enable_big4_shadow",
        "routing_balance_sheet_gating_enabled",
        "equity_no_evidence_not_fail",
        "treat_no_assertion_as_pass",
        # Generic table gates post-date legacy; force off so parity matches baseline
        # without INFO early-exit asymmetry between evidence vs total gates.
        "generic_evidence_gate",
        "enable_generic_total_gate",
        # Document-level cash flow cross-table registry is not in legacy; single-table semantics.
        "cashflow_cross_table_context",
    }
)


_FORCED_FALSE_WHEN_BASELINE_DEFAULT = frozenset(
    {
        "cashflow_cross_table_context",
        "generic_evidence_gate",
        "movement_rollforward",
        "note_structure_engine",
        "classifier_content_override",
        "tax_routing_content_evidence",
        "routing_balance_sheet_gating_enabled",
        "enable_generic_total_gate",
        "treat_no_assertion_as_pass",
        "equity_no_evidence_not_fail",
        "tighten_total_row_keywords",
        "nonbaseline_code_pattern_routing_fallback",
    }
)


def get_feature_flags():
    """Return current feature flags dict (copy).

    In legacy bug compatibility mode, Big4, balance-sheet routing softening, equity/assertion
    softening, generic table total gates, and cashflow cross-table context above
    are forced off so runtime matches legacy baseline even if FEATURE_FLAGS was patched.
    """
    flags = dict(FEATURE_FLAGS)
    # Derive effective legacy compatibility from both old and new flag names.
    legacy_bug_mode = bool(
        flags.get("legacy_bug_compatibility_mode", False)
        or flags.get("legacy_parity_mode", False)
    )
    flags["legacy_bug_compatibility_mode"] = legacy_bug_mode
    # Keep legacy alias coherent for downstream code that still checks it.
    flags["legacy_parity_mode"] = legacy_bug_mode

    if legacy_bug_mode:
        for key in _PARITY_FORCED_FALSE_WHEN_LEGACY_PARITY:
            flags[key] = False
    if flags.get("baseline_authoritative_default", False):
        for key in _FORCED_FALSE_WHEN_BASELINE_DEFAULT:
            flags[key] = False
    return flags
