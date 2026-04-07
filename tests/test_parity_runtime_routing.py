import pandas as pd

from quality_audit.core.cache_manager import AuditContext, LRUCacheManager
from quality_audit.services.audit_service import AuditService


def test_canonical_runtime_has_no_big4_hook():
    context = AuditContext(cache=LRUCacheManager(max_size=8))
    service = AuditService(context=context)
    assert not hasattr(service, "_validate_tables_big4")


def test_non_runtime_validate_tables_still_returns_list():
    context = AuditContext(cache=LRUCacheManager(max_size=8))
    service = AuditService(context=context)
    table = pd.DataFrame(
        [
            ["TÀI SẢN", "", ""],
            ["A", "10", "20"],
        ]
    )

    result = service._validate_tables([(table, "BẢNG CÂN ĐỐI KẾ TOÁN")])
    assert isinstance(result, list)


def test_skip_signature_path_returns_expected_rule(monkeypatch):
    context = AuditContext(cache=LRUCacheManager(max_size=8))
    service = AuditService(context=context)

    monkeypatch.setattr(
        "quality_audit.core.validators.factory.ValidatorFactory.get_validator",
        lambda *_args, **_kwargs: (None, "SKIPPED_FOOTER_SIGNATURE"),
    )

    table = pd.DataFrame([["Footer", "Signed by Director"]])
    result = service._validate_single_table(
        table,
        "Signature table",
        table_context={"heading_source": "paragraph"},
    )

    assert result.rule_id == "SKIPPED_FOOTER_SIGNATURE"
    assert "skip" in result.status.lower() or "footer" in result.status.lower()
