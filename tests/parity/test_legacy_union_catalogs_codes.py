from quality_audit.core.legacy_audit import (
    CROSS_CHECK_TABLES_FORM_1A,
    CROSS_CHECK_TABLES_FORM_1B,
    CROSS_CHECK_TABLES_FORM_3,
    TABLES_NEED_CHECK_SEPARATELY,
    TABLES_NEED_COLUMN_CHECK,
    TABLES_WITHOUT_TOTAL,
    VALID_CODES,
)


def test_legacy_union_forms_restored():
    assert (
        "accounts payable to suppliers classified by payment terms"
        in CROSS_CHECK_TABLES_FORM_1A
    )
    assert "cash and cash equivalents" in CROSS_CHECK_TABLES_FORM_1B
    assert "acquisition of subsidiary" in CROSS_CHECK_TABLES_FORM_3
    assert "changes in owners’ equity" in CROSS_CHECK_TABLES_FORM_3


def test_legacy_union_valid_codes_restored():
    for code in ("234", "235", "241", "242"):
        assert code in VALID_CODES


def test_legacy_union_column_check_not_shrunk():
    required = {
        "borrowings",
        "acquisition of subsidiary",
        "changes in owners’ equity",
        "taxes and others payable to state treasury",
        "taxes receivable from state treasury",
        "long-term deferred expenses",
    }
    assert required.issubset(TABLES_NEED_COLUMN_CHECK)


def test_legacy_union_special_table_sets_not_shrunk():
    assert {
        "investment property held for capital appreciation",
        "finance lease tangible fixed assets",
        "goodwill",
    }.issubset(TABLES_NEED_CHECK_SEPARATELY)
    assert {
        "fair values versus carrying amounts",
        "fees paid and payable to the auditors",
        "geographical segments",
    }.issubset(TABLES_WITHOUT_TOTAL)
