import pandas as pd

from quality_audit.core.cache_manager import AuditContext, LRUCacheManager
from quality_audit.core.legacy_audit.engine import LegacyAuditEngine
from quality_audit.core.validators.base_validator import ValidationResult


def test_legacy_engine_does_not_generic_fallback_for_cash_flow(monkeypatch):
    context = AuditContext(cache=LRUCacheManager(max_size=8))
    engine = LegacyAuditEngine(context=context)
    table = pd.DataFrame([["Code", "Current", "Prior"], ["20", "1", "1"]])

    class _StubCashFlowValidator:
        def validate(self, *_args, **_kwargs):
            return ValidationResult(
                status="FAIL: strict baseline",
                rule_id="CF_STRICT",
                status_enum="FAIL",
                context={},
            )

    monkeypatch.setattr(
        "quality_audit.core.legacy_audit.engine.route_table",
        lambda *_args, **_kwargs: type(
            "_Route",
            (),
            {
                "family": "cash_flow",
                "reason": "code_pattern_fallback",
                "confidence": 0.65,
            },
        )(),
    )
    monkeypatch.setattr(
        engine, "_build_validator", lambda family: _StubCashFlowValidator()
    )

    result = engine.validate_table(table, "unknown", {})
    assert result.rule_id == "CF_STRICT"
    assert result.context.get("legacy_route_fallback") is None
