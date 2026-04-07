import pandas as pd

from quality_audit.core.validators.base_validator import ValidationResult
from quality_audit.services.audit_service import AuditService


def test_baseline_path_strips_nonbaseline_routing_hints(monkeypatch):
    service = AuditService()
    table = pd.DataFrame([["A", "1", "1"]])

    monkeypatch.setattr(
        "quality_audit.services.audit_service.get_feature_flags",
        lambda: {
            "baseline_authoritative_default": True,
            "legacy_bug_compatibility_mode": True,
            "legacy_parity_mode": False,
        },
    )

    captured = {}

    def _legacy_validate(_table, _heading, table_context=None):
        captured.update(table_context or {})
        return ValidationResult(
            status="PASS",
            rule_id="LEGACY",
            status_enum="PASS",
            context={},
        )

    monkeypatch.setattr(service.legacy_engine, "validate_table", _legacy_validate)
    service._validate_single_table(
        table,
        "heading",
        table_context={
            "statement_family": "cash_flow",
            "routing_reason": "table_context_hint",
            "continuation_confidence": 0.9,
            "continuation_evidence": ["x"],
            "statement_group_id": "sg_0001",
        },
    )
    assert "statement_family" not in captured
    assert "routing_reason" not in captured
    assert "continuation_confidence" not in captured
    assert "continuation_evidence" not in captured
    assert captured.get("statement_group_id") == "sg_0001"
