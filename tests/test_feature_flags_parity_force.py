"""Tests: legacy parity forces specific flags off in get_feature_flags() output."""

import pytest

import quality_audit.config.feature_flags as ff

_PARITY_FORCED_KEYS = (
    "enable_big4_engine",
    "enable_big4_shadow",
    "routing_balance_sheet_gating_enabled",
    "equity_no_evidence_not_fail",
    "treat_no_assertion_as_pass",
    "generic_evidence_gate",
    "enable_generic_total_gate",
    "cashflow_cross_table_context",
)


@pytest.mark.parametrize("key", _PARITY_FORCED_KEYS)
def test_get_feature_flags_forces_key_false_when_legacy_parity_on(monkeypatch, key):
    monkeypatch.setitem(ff.FEATURE_FLAGS, "legacy_parity_mode", True)
    for k in _PARITY_FORCED_KEYS:
        monkeypatch.setitem(ff.FEATURE_FLAGS, k, True)
    out = ff.get_feature_flags()
    assert out["legacy_parity_mode"] is True
    assert out[key] is False


def test_get_feature_flags_all_parity_forced_keys_false_together(monkeypatch):
    monkeypatch.setitem(ff.FEATURE_FLAGS, "legacy_parity_mode", True)
    for k in _PARITY_FORCED_KEYS:
        monkeypatch.setitem(ff.FEATURE_FLAGS, k, True)
    out = ff.get_feature_flags()
    for k in _PARITY_FORCED_KEYS:
        assert out[k] is False, k


def test_get_feature_flags_does_not_force_when_legacy_parity_off(monkeypatch):
    monkeypatch.setitem(ff.FEATURE_FLAGS, "legacy_parity_mode", False)
    monkeypatch.setitem(ff.FEATURE_FLAGS, "baseline_authoritative_default", False)
    for k in _PARITY_FORCED_KEYS:
        monkeypatch.setitem(ff.FEATURE_FLAGS, k, True)
    out = ff.get_feature_flags()
    assert out["legacy_parity_mode"] is False
    for k in _PARITY_FORCED_KEYS:
        assert out[k] is True, k


def test_baseline_default_forces_nonbaseline_decision_flags_off(monkeypatch):
    monkeypatch.setitem(ff.FEATURE_FLAGS, "legacy_parity_mode", False)
    monkeypatch.setitem(ff.FEATURE_FLAGS, "baseline_authoritative_default", True)
    monkeypatch.setitem(ff.FEATURE_FLAGS, "cashflow_cross_table_context", True)
    monkeypatch.setitem(ff.FEATURE_FLAGS, "generic_evidence_gate", True)
    monkeypatch.setitem(ff.FEATURE_FLAGS, "movement_rollforward", True)
    monkeypatch.setitem(
        ff.FEATURE_FLAGS, "nonbaseline_code_pattern_routing_fallback", True
    )
    out = ff.get_feature_flags()
    assert out["cashflow_cross_table_context"] is False
    assert out["generic_evidence_gate"] is False
    assert out["movement_rollforward"] is False
    assert out["nonbaseline_code_pattern_routing_fallback"] is False


def test_get_feature_flags_returns_copy_not_same_dict(monkeypatch):
    monkeypatch.setitem(ff.FEATURE_FLAGS, "legacy_parity_mode", True)
    out = ff.get_feature_flags()
    assert out is not ff.FEATURE_FLAGS


def test_corrected_runtime_defaults_enabled():
    out = ff.get_feature_flags()
    assert out["baseline_authoritative_default"] is False
    assert out["heading_fallback_from_table_first_row"] is True
    assert out["heading_inference_v2"] is True
    assert out["classifier_content_override"] is True
    assert out["tax_routing_content_evidence"] is True
    assert out["movement_rollforward"] is True
    assert out["note_structure_engine"] is True
    assert out["tighten_total_row_keywords"] is True
    assert out["cashflow_cross_table_context"] is True
