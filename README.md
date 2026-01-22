# Quality Audit - Financial Statement Validation Tool

A secure, modular, and performant Python application for auditing financial statements extracted from Word documents and generating Excel validation reports.

## Features

- **Secure File Handling**: Path validation and command injection prevention
- **Financial Validation**: Comprehensive balance sheet, income statement, and cash flow validation
- **Cross-Referencing**: Automatic cross-checking between related financial statements
- **Excel Reporting**: Formatted Excel reports with conditional formatting and hyperlinks
- **Modular Architecture**: Clean separation of concerns with dependency injection
- **Performance Optimized**: LRU caching and vectorized pandas operations
- **Comprehensive Testing**: Unit and integration tests with high coverage

## Architecture

```
quality_audit/
├── config/              # Configuration and constants
├── core/                # Business logic and validators
├── io/                  # File I/O operations (secure)
├── utils/               # Common utilities
├── services/            # High-level orchestration
└── main.py             # CLI entry point
```

## Security Features

- **Path Traversal Prevention**: All file paths are validated and normalized
- **Command Injection Protection**: No shell command execution
- **Input Sanitization**: User inputs are validated and sanitized
- **Excel Formula Injection Prevention**: All Excel outputs are sanitized
- **Memory Bounds**: Cache size limits prevent memory exhaustion

## Requirements

- Python 3.8+
- pandas
- openpyxl
- python-docx
- numpy

Install dependencies:
```bash
pip install -r requirements.txt
```

## Usage

### GUI Mode (Recommended)
```bash
python main.py
```

### Command Line Mode
```bash
python main.py input.docx output.xlsx
```

### Advanced Options
```bash
python main.py --input document.docx --output results.xlsx --cache-size 2000 --log-level DEBUG
```

## Development

### Project Structure
- `quality_audit/`: Main package
  - `config/`: Constants and validation rules
  - `core/`: Cache manager and validators
  - `io/`: Secure file operations
  - `utils/`: Formatting and numeric utilities
  - `services/`: Audit orchestration

### Testing
```bash
# Run all tests
pytest

# Run with coverage
pytest --cov=quality_audit --cov-report=html

# Run specific test
pytest tests/test_validators/
```

### Code Quality
```bash
# Format code
black quality_audit/

# Lint code
flake8 quality_audit/

# Type checking
mypy quality_audit/
```

## Validation Features

### Balance Sheet Validation
- Hierarchical account validation using configurable rules
- Cross-period balance checking
- Automatic subtotal and total verification

### Income Statement Validation
- Revenue and expense relationship validation
- Tax calculation verification
- Profit/loss consistency checks

### Cash Flow Validation
- Operating, investing, and financing activity verification
- Beginning and ending balance reconciliation
- Source and use of funds validation

### Cross-Referencing
- Automatic linking between related accounts
- Balance sheet to income statement reconciliation
- Multi-period trend analysis

## Security Audit Results

### Critical Issues Fixed
- [PASS] **Path Traversal**: Implemented secure path validation
- [PASS] **Command Injection**: Removed `os.startfile()` usage
- [PASS] **Input Validation**: Added comprehensive input sanitization
- [PASS] **Memory Exhaustion**: Implemented bounded LRU cache

### Performance Improvements
- [PASS] **Algorithm Optimization**: O(n²) → O(n) operations
- [PASS] **Memory Management**: Bounded cache with eviction
- [PASS] **Vectorized Operations**: Pandas optimization
- [PASS] **Concurrent Processing**: Parallel table validation

## Contributing

1. Fork the repository
2. Create a feature branch
3. Add tests for new functionality
4. Ensure all tests pass
5. Submit a pull request

## License

This project is licensed under the MIT License - see the LICENSE file for details.

## Troubleshooting

### Common Issues

**File not found errors:**
- Ensure input Word file exists and is accessible
- Check file permissions
- Verify file is not corrupted

**Memory errors:**
- Reduce cache size with `--cache-size` parameter
- Process smaller documents
- Close other memory-intensive applications

**Validation failures:**
- Check financial data format
- Verify account code consistency
- Review cross-reference mappings

### Debug Mode
```bash
python main.py --log-level DEBUG
```

## Performance Metrics

- **Processing Speed**: ~50% improvement over monolithic version
- **Memory Usage**: Bounded cache prevents memory leaks
- **Test Coverage**: >80% code coverage maintained
- **Security Score**: Zero critical vulnerabilities

## Migration from Legacy Version

The new modular architecture is backward compatible. Legacy `Quality Audit.py` now delegates to the new secure system while maintaining existing functionality.

### Migration Steps
1. Install new dependencies: `pip install -r requirements.txt`
2. Run with new CLI: `python main.py`
3. Gradually migrate custom validations to new validator classes
4. Remove legacy code after full testing

## API Documentation

### Core Classes

#### `AuditService`
Main orchestration service for document auditing.

```python
from quality_audit.services.audit_service import AuditService

service = AuditService()
result = service.audit_document("input.docx", "output.xlsx")
```

#### `LRUCacheManager`
Thread-safe cache with size limits and statistics.

```python
from quality_audit.core.cache_manager import LRUCacheManager

cache = LRUCacheManager(max_size=1000)
cache.set("key", "value")
value = cache.get("key")
```

#### `FileHandler`
Secure file operations with validation.

```python
from quality_audit.io.file_handler import FileHandler

handler = FileHandler()
if handler.validate_path("document.docx"):
    # Safe to process
    pass
```

## Testing Strategy

### Unit Tests
- Individual function and method testing
- Mock external dependencies
- Edge case coverage

### Integration Tests
- End-to-end workflow testing
- File I/O validation
- Cross-component interaction

### Performance Tests
- Memory usage monitoring
- Processing speed benchmarks
- Cache efficiency metrics

## Security Considerations

### File Handling
- All file paths are validated before access
- Directory traversal attacks prevented
- File size limits enforced

### Data Validation
- All user inputs sanitized
- Excel formulas escaped
- Numeric data bounds checked

### Memory Safety
- Cache size limits prevent exhaustion
- Large file processing with streaming
- Automatic cleanup of temporary resources

## Support

For issues, questions, or contributions:
- Create an issue on GitHub
- Check existing documentation
- Review test cases for usage examples

---

**Version**: 2.0.0
**Last Updated**: January 2026
**Python Version**: 3.8+