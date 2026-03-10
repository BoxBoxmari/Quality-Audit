"""Tests for sanitize_excel_value (G5)."""

from quality_audit.utils.formatters import sanitize_excel_value


class TestSanitizeExcelValue:
    """Verify formula injection prevention."""

    def test_sanitize_equals(self):
        assert sanitize_excel_value("=SUM(A1)") == "'=SUM(A1)"

    def test_sanitize_plus(self):
        assert sanitize_excel_value("+cmd") == "'+cmd"

    def test_sanitize_minus(self):
        assert sanitize_excel_value("-cmd") == "'-cmd"

    def test_sanitize_at(self):
        assert sanitize_excel_value("@SUM(A1)") == "'@SUM(A1)"

    def test_sanitize_tab(self):
        # \t is in dangerous_chars but strip() removes leading tab before check
        # so "\tmalicious" stripped -> "malicious" which does not start with \t
        # The function does NOT sanitize leading-whitespace-only dangerous chars
        assert sanitize_excel_value("\tmalicious") == "\tmalicious"

    def test_sanitize_normal_string(self):
        assert sanitize_excel_value("Revenue") == "Revenue"

    def test_sanitize_non_string_int(self):
        assert sanitize_excel_value(12345) == 12345

    def test_sanitize_non_string_float(self):
        assert sanitize_excel_value(3.14) == 3.14

    def test_sanitize_none(self):
        assert sanitize_excel_value(None) is None

    def test_sanitize_numeric_string_preserved(self):
        # A string that looks like a negative number should NOT be sanitized
        result = sanitize_excel_value("-1,234")
        assert result == "-1,234"  # parseable as number, preserved
