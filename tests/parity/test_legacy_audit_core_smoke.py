from quality_audit.core.legacy_audit import (
    CASH_FLOW_CODE_FORMULAS,
    TABLES_NEED_COLUMN_CHECK,
    VALID_CODES,
)


def test_legacy_audit_core_smoke():
    assert "borrowings" in TABLES_NEED_COLUMN_CHECK
    assert "222" in VALID_CODES
    assert CASH_FLOW_CODE_FORMULAS["50"] == ("20", "30", "40")
