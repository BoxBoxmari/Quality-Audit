# Quality Audit - Security Documentation

## Security Overview

Quality Audit implements multiple security layers to protect against common vulnerabilities and ensure safe file processing.

## Security Measures

### 1. Path Traversal Prevention

**Implementation**: `FileHandler.validate_path_secure()`

**Mechanisms**:
- Path normalization and resolution
- Directory traversal detection (`..` in path parts)
- Base directory validation (paths must be within allowed directory)
- Absolute path restrictions

**Code Location**: `quality_audit/io/file_handler.py`

**Example Attack Prevented**:
```python
# Malicious path like "../../etc/passwd" is rejected
malicious_path = "../../etc/passwd"
assert FileHandler.validate_path_secure(malicious_path) == False
```

### 2. Command Injection Prevention

**Implementation**: `FileHandler.open_file_securely()`

**Mechanisms**:
- No shell command execution
- Platform-specific safe commands:
  - Windows: `explorer.exe` (not `cmd /c start`)
  - macOS: `open`
  - Linux: `xdg-open`
- Path validation before opening
- Timeout protection (10 seconds)

**Code Location**: `quality_audit/io/file_handler.py`

**Example Attack Prevented**:
```python
# Old unsafe approach: subprocess.run(['cmd', '/c', 'start', '', path])
# New safe approach: subprocess.run(['explorer.exe', str(path)])
```

### 3. Input Validation

**Implementation**: Multiple layers

**Numeric Input** (`numeric_utils.py`):
- String length limits (max 1000 characters)
- Bounds checking (max absolute value: 1e15)
- NaN handling

**Tax Rate Input** (`file_handler.py`):
- Regex validation: `^[0-9]+([.,][0-9]+)?$`
- Range validation (0-100%)
- Multiple decimal point prevention
- Input length limits

**Code Locations**:
- `quality_audit/utils/numeric_utils.py`
- `quality_audit/io/file_handler.py`

### 4. File Size Limits

**Implementation**: `FileHandler.MAX_FILE_SIZE_MB = 50`

**Mechanisms**:
- Maximum file size: 50MB
- Prevents memory exhaustion attacks
- Validated before processing

**Code Location**: `quality_audit/io/file_handler.py`

### 5. Extension Whitelisting

**Implementation**: `FileHandler.ALLOWED_EXTENSIONS = {'.docx', '.xlsx'}`

**Mechanisms**:
- Only `.docx` and `.xlsx` files allowed
- Case-insensitive validation
- Rejects all other extensions

**Code Location**: `quality_audit/io/file_handler.py`

### 6. Excel Formula Injection Prevention

**Implementation**: `sanitize_excel_value()` in formatters

**Mechanisms**:
- Escapes formula-initiating characters (`=`, `+`, `-`, `@`)
- Prevents execution of malicious formulas
- Applied to all Excel cell values

**Code Location**: `quality_audit/utils/formatters.py`

### 7. Memory Bounds

**Implementation**: `LRUCacheManager` with `max_size`

**Mechanisms**:
- Configurable cache size limits
- LRU eviction prevents unbounded growth
- Thread-safe operations

**Code Location**: `quality_audit/core/cache_manager.py`

## Security Testing

### Test Coverage
- Path traversal attempts: `tests/test_file_handler_security.py`
- File opening security: `tests/test_file_handler_security.py`
- Input validation: Integrated in component tests

### Security Test Cases
1. Path traversal with various patterns (`../`, `..\\`, etc.)
2. Invalid file extensions
3. Oversized files
4. Malicious Excel formulas
5. Command injection attempts

## OWASP Top 10 Compliance

### A01: Broken Access Control
- **Status**: Protected
- **Measures**: Path validation, file access restrictions

### A02: Cryptographic Failures
- **Status**: Not Applicable
- **Note**: No sensitive data encryption required for this application

### A03: Injection
- **Status**: Protected
- **Measures**: 
  - Command injection prevention
  - Excel formula injection prevention
  - Input validation and sanitization

### A04: Insecure Design
- **Status**: Protected
- **Measures**: Secure by design architecture, dependency injection

### A05: Security Misconfiguration
- **Status**: Protected
- **Measures**: Secure defaults, validation on all inputs

### A06: Vulnerable Components
- **Status**: Monitor
- **Measures**: Regular dependency updates, security audits

### A07: Authentication Failures
- **Status**: Not Applicable
- **Note**: No authentication required for local file processing

### A08: Software and Data Integrity Failures
- **Status**: Protected
- **Measures**: Input validation, file integrity checks

### A09: Security Logging and Monitoring
- **Status**: Partial
- **Measures**: Error logging, cache statistics
- **Future**: Enhanced security event logging

### A10: Server-Side Request Forgery (SSRF)
- **Status**: Not Applicable
- **Note**: No network requests in current implementation

## Security Best Practices

### For Developers

1. **Always use `validate_path_secure()`** for file paths
2. **Never use shell commands** for file operations
3. **Validate all user inputs** before processing
4. **Use `AuditContext`** instead of global state
5. **Sanitize Excel values** before writing
6. **Set cache size limits** to prevent memory issues
7. **Handle exceptions** without exposing internal details

### Code Review Checklist

- [ ] All file paths validated
- [ ] No shell command execution
- [ ] Input validation on all user inputs
- [ ] Bounds checking on numeric values
- [ ] Excel values sanitized
- [ ] Cache size limits enforced
- [ ] Error messages don't leak sensitive info

### P5 Regression Gate Checklist (Quality Audit Fix)

- [ ] **Formula injection (P1):** All text cells written to XLSX go through `sanitize_excel_value()` (prefix `=`, `+`, `-`, `@` with tab or apostrophe); numeric cells are not sanitized. Location: `quality_audit/io/excel_writer.py` and `quality_audit/utils/formatters.py`.
- [ ] **Forensic columns:** XLSX output includes extractor_engine, total_row_method, total_row_index, total_row_confidence, column_classification_method, invariants_failed, heading_source, heading_confidence where applicable.
- [ ] **Structured logging:** No secrets in logs; audit/validator decisions use low-noise structured fields (e.g. total_row_metadata, invariant flags) for observability without PII.
- [ ] **Verifier:** Run `pytest`, `ruff check quality_audit/`; run pipeline on 2 DOCX; compare baseline vs after (FAIL_TOOL_EXTRACT and false FAIL/WARN); confirm XLSX has forensic columns and no formula injection when opening file.

## Incident Response

### If Security Issue Discovered

1. **Immediate**: Disable affected functionality if critical
2. **Assessment**: Determine severity and impact
3. **Fix**: Implement secure solution
4. **Test**: Verify fix with security tests
5. **Document**: Update this document with lessons learned

## Security Updates

### Version 2.0.0 (Current)
- Secure path validation
- Safe file opening
- Input validation enhancements
- Excel formula injection prevention
- Memory bounds enforcement

### Future Enhancements
- [ ] Security event logging
- [ ] Rate limiting for file operations
- [ ] File content validation (malware scanning)
- [ ] Audit trail for all operations
