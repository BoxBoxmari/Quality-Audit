# Quality Audit - Architecture Documentation

## Overview

Quality Audit is a modular Python application for validating financial statements extracted from Word documents. The architecture follows clean architecture principles with clear separation of concerns.

## Repository Layout

- **`quality_audit/`** – Main package (UI, services, core, io, utils, config).
- **`main.py`**, **`quality_audit/cli.py`** – Entry points; **`run_gui.bat`** – GUI launcher.
- **`docs/`** – Architecture, API, security, audit reports, task and feature docs.
- **`scripts/`** – One-off and utility scripts (extract, verify, analysis); see `scripts/README.md`.
- **`tests/`** – Unit, integration, regression tests; **`tests/conftest.py`**, **`tests/fixtures/`**, **`tests/integration/`**, **`tests/io/`**, **`tests/regression/`**, **`tests/core/`**.
- **`reports/`** – Generated or hand-written report artifacts (e.g. shortlist, verification).
- **`legacy/`** – Legacy script **`Quality Audit.py`**.
- **`README.md`**, **`CHANGELOG.md`**, **`openmemory.md`**, **`pyproject.toml`**, **`requirements.txt`** – Project metadata and config.

## Architecture Layers

### 1. Presentation Layer (GUI)

- **Location**: `quality_audit/ui/`
- **Components**:
  - `tk_cli_gui.py`: Tkinter-based Graphical User Interface with status bar, in-place editing, and settings persistence
  - `styles.py`: UI styling and themes (dark theme with accent colors)
  - `settings_store.py`: JSON-based settings persistence for GUI preferences
  - `command_format.py`: Command preview formatting utilities
- **Responsibility**: User interaction, command construction, log visualization, and state management

### 2. Entry Point Layer

- **Files**: `main.py`, `quality_audit/cli.py`
- **Responsibility**: CLI interface, argument parsing, dependency initialization
- **Dependencies**: All service and IO layers

### 2. Service Layer

- **Location**: `quality_audit/services/`
- **Components**:
  - `AuditService`: Main orchestration service
  - `BaseService`: Base class for all services
  - `batch_processor.py`: Batch processing utilities
- **Responsibility**: High-level business logic orchestration

### 3. Core Business Logic Layer

- **Location**: `quality_audit/core/`
- **Components**:
  - `validators/`: Financial statement validators (BalanceSheet, IncomeStatement, CashFlow, Equity, Tax, Generic)
  - `cache_manager.py`: LRU cache implementation and AuditContext
  - `diff_engine.py`: Diff and comparison utilities
  - `repositories/`: Data access layer (FinancialDataRepository)
  - `routing/`: Table type classification (TableTypeClassifier)
  - `exceptions.py`: Custom exception classes
- **Responsibility**: Business rules, validation logic, data access
- **Note**: Tax rate configuration lives in `quality_audit/config/tax_rate.py`.

### 4. IO Layer

- **Location**: `quality_audit/io/`
- **Components**:
  - `word_reader.py`: Word document reading (sync and async)
  - `excel_writer.py`: Excel report generation
  - `file_handler.py`: Secure file operations
  - `extractors/`: Table extraction (OOXML, python-docx, docx-to-html, table isolator, token mapper)
- **Responsibility**: File I/O operations with security

**Table extraction engines (IO / data flow)**  
Thứ tự ưu tiên trích bảng từ Word: OOXML (XML trực tiếp) → python-docx → docx-to-html → render-first (DOCX→PDF→ảnh→OCR→grid) → legacy. Luồng **render-first** cần thêm Python libs (Pillow, opencv-python, pytesseract, PyMuPDF, pdf2image) và **binary hệ thống** (Poppler, Tesseract, LibreOffice) cài trên từng máy/OS; pip không cài các binary này. Chi tiết phụ thuộc: `docs/IT-DEPENDENCIES.md`, `README.md`, `requirements.txt`.

### 5. Utilities Layer

- **Location**: `quality_audit/utils/`
- **Components**:
  - `numeric_utils.py`: Numeric parsing and validation
  - `formatters.py`: Data formatting utilities
  - `column_detector.py`, `row_classifier.py`: Column/row detection and classification
  - `table_normalizer.py`, `table_canonicalizer.py`: Table normalization and canonical form
  - `chunk_processor.py`: Chunked processing utilities
  - `telemetry_collector.py`: Observability and telemetry
- **Responsibility**: Common utility functions

### 6. Configuration Layer

- **Location**: `quality_audit/config/`
- **Components**:
  - `constants.py`: Application constants
  - `validation_rules.py`: Financial validation rules
  - `feature_flags.py`: Feature flags (e.g. cashflow_cross_table_context)
  - `tax_rate.py`: Tax rate configuration and resolution
- **Responsibility**: Configuration and business rules

## Design Patterns

### Dependency Injection

- Services receive dependencies through constructor injection
- `AuditContext` encapsulates cache and marks, eliminating global state
- Enables testability and flexibility

### Factory Pattern

- `ValidatorFactory`: Creates appropriate validators based on table content
- Centralizes validator selection logic

### Repository Pattern

- `FinancialDataRepository`: Abstracts data access operations
- Provides clean interface for storing/retrieving financial data
- Makes it easy to swap implementations

### Strategy Pattern

- Different validators implement the same `BaseValidator` interface
- Allows runtime selection of validation strategy

## Data Flow

```text
Word Document
    ↓
WordReader (extract tables)
    ↓
AuditService (orchestrate)
    ↓
ValidatorFactory (select validator)
    ↓
Specific Validator (validate table)
    ↓
FinancialDataRepository (store/retrieve cross-ref data)
    ↓
ExcelWriter (generate report)
    ↓
Excel File
```

## Component Interactions

### AuditService

- Coordinates the entire audit workflow
- Manages context (cache and marks)
- Delegates to validators via factory
- Orchestrates report generation

### Validators

- Implement `BaseValidator` interface
- Use `FinancialDataRepository` for cross-referencing (future)
- Currently use global cache for backward compatibility
- Return `ValidationResult` objects

#### Code Column Exclusion Strategy

- **Primary detection**: `_detect_code_column(df)` in `BaseValidator` identifies the Code column by name/position.
- **Fallback heuristics**: When primary returns `None`, GenericValidator applies: (1) column name matching `r'^(code|mã|ma)'` (case-insensitive); (2) first column with >70% values matching code patterns (`r'^\d{1,3}[A-Z]?` or `r'^[IVX]+\.'`). If detected, that column is excluded from numeric normalization and sum checks.
- **Unified exclusion**: Both `GenericTableValidator` and `TaxValidator._validate_tax_remaining_tables` exclude the Code column from `df_numeric`, block sums (`find_block_sum`), grand total comparison, and `_validate_column_totals` so Code values (e.g. 100, 440) do not trigger "Grand total – Cột X: 100 vs 440" false positives.
- **Diagnostic logging (Pattern C)**: When `sum_detail == 0` and `total_on_table > threshold`, a debug log records `start_idx`, `block_end`, `code_col`, and a sample of `df_numeric` for that column to diagnose block boundary errors, mistaken Code exclusion, or normalize→NaN.

### Cache Manager

- `LRUCacheManager`: Thread-safe LRU cache
- `AuditContext`: Encapsulates cache and marks
- Global instances deprecated but maintained for compatibility

## Security Architecture

### Path Validation

- All file paths validated before access
- Directory traversal prevention
- File size limits enforced
- Extension whitelisting

### File Opening

- Platform-specific safe commands
- No shell command execution
- Input validation before opening

### Input Sanitization

- Numeric input bounds checking
- String length limits
- Regex validation for structured inputs

## Performance Optimizations

### Vectorized Operations

- Pandas vectorized operations in validators
- Reduced loop overhead for large datasets
- Improved performance on large financial statements

### Async Processing

- `AsyncWordReader` for concurrent file I/O
- ThreadPoolExecutor for I/O-bound operations
- Better resource utilization

### Caching Strategy

- LRU cache with configurable size
- TTL support for time-sensitive data
- Thread-safe operations

### Advanced Table Processing (SCRUM-6)

- **TableNormalizer**: Centralized logic for whitespace normalization, multi-row header merging, and canonical column detection.
- **ColumnDetector**: Advanced synonym-based detection for financial columns (Code, Current Year, Prior Year).
- **RowClassifier**: Intelligent row classification (Data vs Section Title vs Subtotal) using cross-column patterns.
- **Structural Validation**: Special handling for movement tables (Beginning + delta = Ending) and subtotal exclusion to reduce false positives.
- **Structured Diagnostics**: `ValidationResult` includes `detected_columns` and `block_indices` for transparency.

## Extension Points

### Adding New Validators

1. Create new validator class inheriting from `BaseValidator`
2. Implement `validate()` method
3. Register in `ValidatorFactory.get_validator()`

### Adding New Repository Methods

1. Add method to `FinancialDataRepository`
2. Use consistent naming: `save_*_data()`, `get_*_data()`
3. Update tests

### Adding New Services

1. Inherit from `BaseService`
2. Use `AuditContext` for state management
3. Follow dependency injection pattern

## Migration Path

### From Global State to DI

1. Create `AuditContext` instance
2. Pass to service constructors
3. Services use `self.context` instead of globals
4. Global instances remain for backward compatibility

### From Direct Cache Access to Repository

1. Inject `FinancialDataRepository` into validators
2. Replace `cross_check_cache.get/set` with repository methods
3. Update tests to use repository mocks

## Testing Strategy

### Unit Tests

- Test individual components in isolation
- Mock dependencies
- Focus on business logic

### Integration Tests

- Test component interactions
- Use real file I/O where appropriate
- Verify end-to-end workflows

### Performance Tests

- Benchmark critical operations
- Measure improvements from optimizations
- Set performance budgets

## Future Enhancements

1. **Full Repository Pattern Adoption**: Update all validators to use repository
2. **Async Service Layer**: Make AuditService async for better concurrency
3. **Database Backend**: Replace cache with persistent database
4. **Plugin System**: Allow custom validators via plugins
5. **API Layer**: REST API for remote auditing
