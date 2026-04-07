import pandas as pd

from quality_audit.core.cache_manager import AuditContext
from quality_audit.core.validators.income_statement_validator import (
    IncomeStatementValidator,
)
from quality_audit.services.audit_service import AuditService


def test_retired_canonical_code_injection_hook_is_absent():
    service = AuditService()
    assert not hasattr(service, "_inject_canonical_row_codes")


def test_income_validator_uses_canonical_code_column_when_present():
    validator = IncomeStatementValidator(context=AuditContext())
    table = pd.DataFrame(
        {
            "Description": [
                "Doanh thu",
                "Giá vốn",
                "Lợi nhuận gộp",
            ],
            "__canonical_code__": ["01", "11", "20"],
            "2024": [100.0, 70.0, 30.0],
            "2023": [90.0, 60.0, 30.0],
        }
    )
    result = validator.validate(table, heading="Income statement", table_context={})
    assert result.context.get("failure_reason_code") != "MISSING_CODE_COLUMN"
