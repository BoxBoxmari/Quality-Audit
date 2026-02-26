# Quality Audit - Financial Statement Validation Tool

A secure, modular, and performant Python application for auditing financial statements extracted from Word documents and generating Excel validation reports.

## Features

- **Secure File Handling**: Path validation and command injection prevention
- **Financial Validation**: Comprehensive balance sheet, income statement, and cash flow validation
- **Cross-Referencing**: Automatic cross-checking between related financial statements
- **Excel Reporting**: Formatted Excel reports with conditional formatting and hyperlinks
- **Modular Architecture**: Clean separation of concerns with dependency injection
- **Performance Optimized**: LRU caching and vectorized pandas operations
- **Robust Table Normalization**: Advanced header detection, synonym matching, and whitespace normalization (SCRUM-6)
- **False Positive Reduction**: Automatic detection of movement tables and subtotal-recalculation logic
- **Comprehensive Testing**: Unit and integration tests with high coverage
- **Utility Scripts**: Suite of diagnostic and analysis tools in `scripts/` (analyze failures, verify installation)
- **GUI Enhancements**: Status bar with elapsed time, in-place tax rate editing, settings persistence

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

- **Python**: 3.8+
- **Core (required for main flow)**: pandas, numpy, openpyxl, python-docx; lxml recommended for OOXML extraction.

### Minimal run (main flow only)

Luồng chính: OOXML / python-docx → trích bảng → validate → Excel. Chỉ cần cài Python packages:

```bash
pip install -r requirements.txt
```

Hoặc môi trường production tối thiểu:

```bash
pip install -r requirements-production.txt
```

### Render-first (optional)

Nếu bật đường DOCX → PDF → ảnh → OCR để trích bảng phức tạp, cần thêm:

- **Python (optional)**: Pillow, opencv-python, pytesseract, PyMuPDF, pdf2image. Thiếu thì tool tự fallback sang luồng legacy, không crash.
- **Binary hệ thống (bắt buộc cho render-first)**: Các chương trình cài trên OS, **không** cài bằng `pip`. Khi đem tool sang máy khác phải cài lại trên từng máy/theo từng OS:
  - **Poppler**: công cụ PDF (có `pdftoppm`). Cài: Windows (Chocolatey: `choco install poppler`), macOS (`brew install poppler`), Linux (`apt install poppler-utils`).
  - **Tesseract**: OCR. Cài: Windows/macOS/Linux — tải installer hoặc package tương ứng.
  - **LibreOffice** (headless `soffice`): chuyển DOCX → PDF. Cài bản desktop hoặc headless theo OS.

`pip install -r requirements.txt` **không** cài giúp Poppler, Tesseract hay LibreOffice; phải cài thủ công trên từng môi trường.

## Usage

### Command Line Mode

Process all .docx files in a folder:

```bash
python main.py /path/to/input/folder
```

The tool will automatically:

- Find all `.docx` files in the specified folder
- Process them with optimal concurrency
- Save results to `results/` folder in the tool directory

### Advanced Options

```bash
python main.py "/path/to/input/folder" --cache-size 2000 --log-level DEBUG --previous-output "previous_results.xlsx" --tax-rate-mode all --tax-rate 20
```

**Options:**

- `input_folder`: Path to folder containing .docx files (required)
- `--cache-size`: Maximum cache size (default: 1000)
- `--log-level`: Logging level - DEBUG, INFO, WARNING, ERROR (default: INFO)
- `--previous-output`: Path to previous audit Excel output for triage data carry-forward
- `--output-dir`: Custom directory for storing results
- `--tax-rate-mode`: Tax rate resolution mode ("prompt", "all", "individual")
- `--tax-rate`: Tax rate percentage for "all" mode (e.g., 20 for 20%)
- `--tax-rate-map`: Path to JSON mapping file for "individual" mode

### GUI Mode

Launch the user-friendly terminal-themed GUI:

```bash
run_gui.bat
# OR
python -m quality_audit.ui.tk_cli_gui
```

**GUI Features:**

- **Terminal Theme**: Consistent formatting with CLI output
- **Command Preview**: See the exact command being constructed
- **Tax Rate Management**: Configure rates for files individually or in bulk with in-place editing
- **Live Logs**: Real-time streaming of validation logs
- **Status Bar**: Real-time status with colored indicators and elapsed time tracking
- **Settings Persistence**: Banner preference and other UI settings are saved automatically
- **Safe Mode**: Validate paths before execution

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
black quality_audit/ scripts/ main.py

# Lint and auto-fix
ruff check --fix quality_audit/ scripts/ main.py

# Lint code
flake8 quality_audit/ scripts/ main.py

# Type checking
mypy quality_audit/ scripts/ main.py --ignore-missing-imports
```

## Migration guide

For breaking changes and upgrade notes, see [CHANGELOG.md](CHANGELOG.md). Summary for v2.0.0:

- `WordReader.read_tables_with_headings()` returns 3-tuple `(df, heading, table_context)` by default; use `include_context=False` for 2-tuple backward compatibility.
- `GenericTableValidator.validate()` accepts optional `table_context` for extraction-quality gating.
- Global `cross_check_marks` is deprecated; use `AuditContext.marks` instead.
- CLI can be invoked via `python -m quality_audit.cli` or `main.py`.

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

The new modular architecture supersedes the legacy version. The old `Quality Audit.py` script has been removed in version 2.0.

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

## Utility Scripts

The `scripts/` directory contains tools for analysis and debugging:

- `scripts/verify_installation.py`: Check if environment and dependencies are correctly set up. Verifies Python version, required packages, and system configuration.
- `scripts/analyze_output.py`: Analyze validation results from Excel files. Counts PASS/FAIL/WARN/ERROR statuses and provides summary statistics. Accepts file paths as command-line arguments.
- `scripts/analyze_failures.py`: Analyze FAIL/WARN patterns in Excel output files. Identifies common error patterns and routing issues.

**Usage**:

```bash
# Verify installation
python scripts/verify_installation.py

# Analyze output files
python scripts/analyze_output.py output1.xlsx output2.xlsx
python scripts/analyze_output.py output1.xlsx --json  # JSON output format

# Analyze failures
python scripts/analyze_failures.py output1.xlsx output2.xlsx
```

## Support

For issues, questions, or contributions:

- Create an issue on GitHub
- Check existing documentation
- Review test cases for usage examples

---

**Version**: 2.1.0
**Last Updated**: February 2026
**Python Version**: 3.8+
