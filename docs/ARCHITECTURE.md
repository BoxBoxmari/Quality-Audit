# Quality Audit - Architecture Documentation

## Overview

Quality Audit is a modular Python application for validating financial statements extracted from Word documents. The architecture follows clean architecture principles with clear separation of concerns.

## Architecture Layers

### 1. Entry Point Layer
- **File**: `main.py`
- **Responsibility**: CLI interface, argument parsing, dependency initialization
- **Dependencies**: All service and IO layers

### 2. Service Layer
- **Location**: `quality_audit/services/`
- **Components**:
  - `AuditService`: Main orchestration service
  - `BaseService`: Base class for all services
- **Responsibility**: High-level business logic orchestration

### 3. Core Business Logic Layer
- **Location**: `quality_audit/core/`
- **Components**:
  - `validators/`: Financial statement validators (BalanceSheet, IncomeStatement, etc.)
  - `cache_manager.py`: LRU cache implementation and AuditContext
  - `repositories/`: Data access layer (FinancialDataRepository)
  - `exceptions.py`: Custom exception classes
- **Responsibility**: Business rules, validation logic, data access

### 4. IO Layer
- **Location**: `quality_audit/io/`
- **Components**:
  - `word_reader.py`: Word document reading (sync and async)
  - `excel_writer.py`: Excel report generation
  - `file_handler.py`: Secure file operations
- **Responsibility**: File I/O operations with security

### 5. Utilities Layer
- **Location**: `quality_audit/utils/`
- **Components**:
  - `numeric_utils.py`: Numeric parsing and validation
  - `formatters.py`: Data formatting utilities
- **Responsibility**: Common utility functions

### 6. Configuration Layer
- **Location**: `quality_audit/config/`
- **Components**:
  - `constants.py`: Application constants
  - `validation_rules.py`: Financial validation rules
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

```
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
