"""
Regression tests for reconciliation cache scoping.
"""

from quality_audit.core.cache_manager import (
    AuditContext,
    LRUCacheManager,
    cross_check_cache,
)
from quality_audit.services.financial_reconciliation_service import (
    FinancialReconciliationService,
)


def test_reconciliation_prefers_context_cache_over_global():
    context = AuditContext(cache=LRUCacheManager(max_size=100))
    context.cache.set("revenue", (100.0, 90.0))
    cross_check_cache.set("revenue", (999.0, 999.0))

    service = FinancialReconciliationService(context=context)
    report = service.reconcile(
        {"Revenue": {"total_row_value_cy": 100.0, "total_row_value_py": 90.0}}
    )

    assert len(report.items) == 1
    assert report.items[0].status == "MATCH"
    assert report.items[0].fs_value_cy == 100.0
    assert report.items[0].fs_value_py == 90.0
