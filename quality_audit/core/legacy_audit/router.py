"""
Baseline-authoritative table routing for default runtime.

This router is intentionally conservative:
- heading/catalog first
- extraction metadata is a hint only
- no modern classifier ownership in default path
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Any, Dict, Optional

import pandas as pd

from quality_audit.config.feature_flags import get_feature_flags

from .catalogs import (
    CROSS_CHECK_TABLES_FORM_1,
    CROSS_CHECK_TABLES_FORM_1A,
    CROSS_CHECK_TABLES_FORM_1B,
    CROSS_CHECK_TABLES_FORM_2,
    CROSS_CHECK_TABLES_FORM_3,
)
from .headings import HEADING_ALIASES


@dataclass(frozen=True)
class LegacyRoute:
    family: str
    reason: str
    confidence: float


def _norm(s: str) -> str:
    return " ".join((s or "").strip().lower().split())


def _lookup_heading_family(heading_lower: str) -> Optional[str]:
    if not heading_lower:
        return None
    for family, aliases in HEADING_ALIASES.items():
        if any(alias in heading_lower for alias in aliases):
            return family
    return None


def _catalog_hint(heading_lower: str) -> Optional[str]:
    union_cross = (
        CROSS_CHECK_TABLES_FORM_1
        | CROSS_CHECK_TABLES_FORM_1A
        | CROSS_CHECK_TABLES_FORM_1B
        | CROSS_CHECK_TABLES_FORM_2
        | CROSS_CHECK_TABLES_FORM_3
    )
    if heading_lower in union_cross:
        return "note"
    return None


def _infer_family_from_codes(table: pd.DataFrame) -> Optional[str]:
    """Legacy-style code-density fallback for heading-indeterminate tables."""
    found_codes: set[str] = set()
    scan_rows = min(len(table), 60)
    scan_cols = min(len(table.columns), 6)
    for i in range(scan_rows):
        for j in range(scan_cols):
            try:
                val = str(table.iloc[i, j]).strip()
            except Exception:
                continue
            m = re.match(r"^(\d{2,3})[A-Za-z]?$", val)
            if m:
                found_codes.add(m.group(1))

    bs_matches = len(found_codes.intersection({"100", "110", "270", "300", "440"}))
    is_matches = len(
        found_codes.intersection({"01", "11", "20", "21", "22", "30", "50", "60"})
    )
    cf_matches = len(found_codes.intersection({"20", "30", "40", "50", "60", "70"}))

    if bs_matches >= 3:
        return "balance_sheet"
    if cf_matches >= 3:
        return "cash_flow"
    if is_matches >= 3:
        return "income_statement"
    return None


def route_table(
    table: pd.DataFrame, heading: Optional[str], table_context: Optional[Dict[str, Any]]
) -> LegacyRoute:
    """
    Resolve baseline family for validation.
    Families: balance_sheet, income_statement, cash_flow, equity, tax_note, generic_note.
    """
    heading_lower = _norm(heading or "")
    note_disambiguation_keywords = (
        "note",
        "thuyết minh",
        "disclosure",
        "recognised in",
        "is recognised",
        "details of",
        "chi tiết",
        "schedule of",
        "policy",
        "accounting policy",
    )

    if any(k in heading_lower for k in note_disambiguation_keywords):
        if "tax" in heading_lower or "thuế" in heading_lower:
            return LegacyRoute("tax_note", "note_disambiguation:tax_note", 0.9)
        return LegacyRoute("generic_note", "note_disambiguation:generic_note", 0.9)

    # 1) Heading-first legacy behavior.
    family = _lookup_heading_family(heading_lower)
    if family == "notes":
        return LegacyRoute("generic_note", "heading_alias:notes", 0.9)
    if family:
        return LegacyRoute(family, f"heading_alias:{family}", 0.95)

    # 2) Preserve simple tax heading behavior from legacy.
    if "tax" in heading_lower or "thuế" in heading_lower:
        return LegacyRoute("tax_note", "heading_keyword:tax", 0.8)

    # 3) Catalog hint when heading exactly matches known legacy note tables.
    cat = _catalog_hint(heading_lower)
    if cat == "note":
        return LegacyRoute("generic_note", "legacy_catalog:cross_check_table", 0.75)

    # 4) Conservative code-pattern fallback when heading/catalog are indeterminate.
    # 4) Optional nonbaseline fallback: code-pattern inference can shift
    # semantics for heading-indeterminate tables, so keep it gated off by default.
    inferred = _infer_family_from_codes(table)
    # Conservative baseline-safe adapter:
    # allow only balance-sheet inference by code density as low-risk fallback.
    if inferred == "balance_sheet":
        return LegacyRoute("balance_sheet", "code_pattern_fallback_balance_only", 0.6)
    flags = get_feature_flags()
    if flags.get("nonbaseline_code_pattern_routing_fallback", False) and inferred:
        return LegacyRoute(inferred, "code_pattern_fallback", 0.65)

    # 5) Conservative default.
    return LegacyRoute("generic_note", "fallback:generic_note", 0.4)
