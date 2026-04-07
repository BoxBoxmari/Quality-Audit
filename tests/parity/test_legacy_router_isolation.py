import pandas as pd

import quality_audit.config.feature_flags as ff
from quality_audit.core.legacy_audit.router import route_table


def test_router_ignores_statement_family_hint_when_heading_is_indeterminate():
    table = pd.DataFrame(
        [
            ["Code", "Current", "Prior"],
            ["999", "10", "9"],
        ]
    )
    route = route_table(
        table,
        heading="",
        table_context={"statement_family": "cash_flow"},
    )
    assert route.reason != "table_context_hint"
    assert route.family == "generic_note"


def test_router_heading_still_authoritative_when_available():
    table = pd.DataFrame([["A", "1", "1"]])
    route = route_table(
        table,
        heading="Statement of financial position",
        table_context={"statement_family": "cash_flow"},
    )
    assert route.family == "balance_sheet"
    assert route.reason.startswith("heading_alias:")


def test_router_does_not_use_code_pattern_fallback_by_default(monkeypatch):
    monkeypatch.setitem(
        ff.FEATURE_FLAGS, "nonbaseline_code_pattern_routing_fallback", False
    )
    table = pd.DataFrame(
        [
            ["Code", "Current", "Prior"],
            ["20", "100", "90"],
            ["30", "50", "45"],
            ["70", "10", "8"],
        ]
    )
    route = route_table(table, heading="", table_context={})
    assert route.family == "generic_note"
    assert route.reason == "fallback:generic_note"


def test_router_can_enable_code_pattern_fallback_in_nonbaseline_mode(monkeypatch):
    monkeypatch.setitem(ff.FEATURE_FLAGS, "baseline_authoritative_default", False)
    monkeypatch.setitem(
        ff.FEATURE_FLAGS, "nonbaseline_code_pattern_routing_fallback", True
    )
    table = pd.DataFrame(
        [
            ["Code", "Current", "Prior"],
            ["20", "100", "90"],
            ["30", "50", "45"],
            ["70", "10", "8"],
        ]
    )
    route = route_table(table, heading="", table_context={})
    assert route.family == "cash_flow"
    assert route.reason == "code_pattern_fallback"
