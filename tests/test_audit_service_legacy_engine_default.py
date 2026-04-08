import pandas as pd

from quality_audit.core.validators.base_validator import ValidationResult
from quality_audit.services.audit_service import AuditService


def test_validate_single_table_does_not_expose_legacy_engine_owner():
    service = AuditService()
    assert hasattr(service, "legacy_engine")


def test_validate_single_table_uses_validator_factory_in_non_runtime_path(monkeypatch):
    service = AuditService()
    table = pd.DataFrame([["Amount", "100", "90"]])

    class _StubValidator:
        def validate(self, *_args, **_kwargs):
            return ValidationResult(
                status="PASS: modern",
                rule_id="MODERN_RULE",
                status_enum="PASS",
                context={"validator_type": "StubModernValidator"},
            )

    monkeypatch.setattr(
        "quality_audit.core.validators.factory.ValidatorFactory.get_validator",
        lambda *_args, **_kwargs: (_StubValidator(), None),
    )

    result = service._validate_single_table(table, "Any heading", table_context={})
    assert result.rule_id == "MODERN_RULE"
    assert result.context.get("validator_type") == "StubModernValidator"
