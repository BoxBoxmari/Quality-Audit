"""
Security-focused tests for FileHandler.
"""

from quality_audit.io.file_handler import FileHandler


class TestFileHandlerSecurity:
    """Security tests for file path validation and file opening."""

    def test_path_traversal_prevention(self, tmp_path):
        """Test that path traversal attempts are rejected."""
        # Create a test file
        test_file = tmp_path / "test.docx"
        test_file.write_bytes(b"test content")

        # Test various path traversal attempts
        malicious_paths = [
            "../test.docx",
            "../../etc/passwd",
            "..\\..\\windows\\system32",
            str(tmp_path / ".." / "test.docx"),
            str(tmp_path / "subdir" / ".." / ".." / "test.docx"),
        ]

        for malicious_path in malicious_paths:
            # Should reject or fail to validate
            result = FileHandler.validate_path_secure(malicious_path, {".docx"})
            assert result is False, f"Path traversal not prevented: {malicious_path}"

    def test_secure_path_validation_with_valid_file(self, tmp_path):
        """Test secure path validation with valid file."""
        test_file = tmp_path / "valid.docx"
        test_file.write_bytes(b"test content")

        result = FileHandler.validate_path_secure(str(test_file), {".docx"})
        assert result is True

    def test_secure_path_validation_rejects_invalid_extensions(self, tmp_path):
        """Test that invalid file extensions are rejected."""
        test_file = tmp_path / "test.exe"
        test_file.write_bytes(b"test content")

        result = FileHandler.validate_path_secure(str(test_file), {".docx", ".xlsx"})
        assert result is False

    def test_secure_path_validation_rejects_large_files(self, tmp_path):
        """Test that files exceeding size limit are rejected."""
        # Create a large file (simulate)
        test_file = tmp_path / "large.docx"
        # Write enough data to exceed 50MB limit
        large_content = b"x" * (51 * 1024 * 1024)  # 51MB
        test_file.write_bytes(large_content)

        result = FileHandler.validate_path_secure(str(test_file), {".docx"})
        assert result is False

    def test_secure_file_opening_validates_path(self, tmp_path):
        """Test that secure file opening validates path first."""
        invalid_path = tmp_path / "nonexistent.docx"

        result = FileHandler.open_file_securely(str(invalid_path))
        assert result is False

    def test_secure_file_opening_with_valid_file(self, tmp_path):
        """Test secure file opening with valid file (if system supports it)."""
        test_file = tmp_path / "test.xlsx"
        test_file.write_bytes(b"test content")

        # This may fail on systems without default applications,
        # but should not raise security errors
        try:
            result = FileHandler.open_file_securely(str(test_file))
            # Result can be True or False depending on system capabilities
            assert isinstance(result, bool)
        except Exception as e:
            # Should not raise security-related exceptions
            assert "security" not in str(e).lower()
