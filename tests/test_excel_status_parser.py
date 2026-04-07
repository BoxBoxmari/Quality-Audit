from quality_audit.io.excel_writer import ExcelWriter


class TestExcelLegacyStatusParser:
    def test_icon_only_warning_is_warn(self):
        assert ExcelWriter._legacy_status_to_enum("⚠️ Something needs review") == "WARN"

    def test_warn_keyword_is_warn(self):
        assert ExcelWriter._legacy_status_to_enum("warn: check note mapping") == "WARN"

    def test_fail_keyword_is_fail(self):
        assert ExcelWriter._legacy_status_to_enum("FAIL: extraction mismatch") == "FAIL"
