# Quality Audit - API Documentation

## Core API Reference

### AuditService

Main service for orchestrating financial statement audits.

#### Constructor

```python
AuditService(
    context: Optional[AuditContext] = None,
    cache_manager: Optional[LRUCacheManager] = None,
    word_reader: Optional[WordReader] = None,
    excel_writer: Optional[ExcelWriter] = None,
    file_handler: Optional[FileHandler] = None
)
```

**Parameters**:

- `context`: Audit context with cache and marks (preferred)
- `cache_manager`: Cache manager (deprecated, use context instead)
- `word_reader`: Word document reader
- `excel_writer`: Excel report writer
- `file_handler`: Secure file handler

#### Methods

##### `audit_document(word_path: str, excel_path: str) -> Dict[str, Any]`

Execute complete audit workflow.

**Parameters**:

- `word_path`: Path to input Word document
- `excel_path`: Path to output Excel file

**Returns**:

```python
{
    'success': bool,
    'tables_processed': int,
    'results': List[Dict],
    'output_path': str,
    'error': Optional[str],
    'error_type': Optional[str]
}
```

**Raises**:

- `SecurityError`: If file path is invalid or unsafe
- `FileProcessingError`: If file processing fails
- `ValidationError`: If validation fails
- `QualityAuditError`: For unexpected errors

**Example**:

```python
from quality_audit.services.audit_service import AuditService
from quality_audit.core.cache_manager import AuditContext, LRUCacheManager

context = AuditContext(cache=LRUCacheManager(max_size=1000))
service = AuditService(context=context)

result = service.audit_document("input.docx", "output.xlsx")
if result['success']:
    print(f"Processed {result['tables_processed']} tables")
```

### AuditContext

Context object for audit operations, replacing global state.

#### Constructor

```python
AuditContext(cache: Optional[LRUCacheManager] = None)
```

**Parameters**:

- `cache`: Cache manager instance (creates new one if not provided)

#### Properties

- `cache`: LRUCacheManager instance
- `marks`: Set of cross-check marks

#### Methods

##### `clear() -> None`

Clear both cache and marks.

### TaxRateConfig

Configuration object for tax rate resolution.

#### Constructor

```python
TaxRateConfig(
    mode: str = "prompt",
    all_rate: Optional[float] = None,
    map_data: Optional[Dict[str, float]] = None,
    default_rate: Optional[float] = None
)
```

**Parameters**:

- `mode`: Resolution mode ("prompt", "all", "individual")
- `all_rate`: Tax rate for "all" mode (decimal, e.g. 0.20)
- `map_data`: Dictionary mapping filenames to tax rates
- `default_rate`: Default rate for "individual" mode fallback

### LRUCacheManager

Thread-safe LRU cache with configurable size limits.

#### Constructor

```python
LRUCacheManager(max_size: int = 1000, ttl_seconds: Optional[float] = None)
```

**Parameters**:

- `max_size`: Maximum number of cache entries
- `ttl_seconds`: Time-to-live in seconds (None for no expiration)

#### Methods

##### `get(key: str) -> Optional[Any]`

Get value from cache.

**Returns**: Cached value or None if not found/expired

##### `set(key: str, value: Any) -> None`

Set value in cache with LRU eviction.

##### `delete(key: str) -> bool`

Delete entry from cache.

**Returns**: True if key was found and deleted

##### `clear() -> None`

Clear all cache entries.

##### `get_stats() -> Dict[str, Any]`

Get cache statistics.

**Returns**:

```python
{
    'size': int,
    'max_size': int,
    'hits': int,
    'misses': int,
    'evictions': int,
    'sets': int,
    'hit_rate': float,
    'ttl_seconds': Optional[float]
}
```

### FinancialDataRepository

Repository for financial data access and cross-referencing.

#### Constructor

```python
FinancialDataRepository(cache: LRUCacheManager)
```

**Parameters**:

- `cache`: Cache manager instance

#### Methods

##### `save_balance_sheet_data(account: str, cy: float, py: float) -> None`

Save balance sheet account data.

##### `get_balance_sheet_data(account: str) -> Optional[Tuple[float, float]]`

Retrieve balance sheet account data.

##### `save_income_statement_data(account: str, cy: float, py: float) -> None`

Save income statement account data.

##### `get_income_statement_data(account: str) -> Optional[Tuple[float, float]]`

Retrieve income statement account data.

##### `save_cash_flow_data(account: str, cy: float, py: float) -> None`

Save cash flow statement account data.

##### `get_cash_flow_data(account: str) -> Optional[Tuple[float, float]]`

Retrieve cash flow statement account data.

##### `save_account_data(account: str, cy: float, py: float, statement_type: str = "generic") -> None`

Save account data with custom statement type prefix.

##### `get_account_data(account: str, statement_type: str = "generic") -> Optional[Tuple[float, float]]`

Retrieve account data with custom statement type prefix.

##### `clear_all() -> None`

Clear all cached financial data.

### FileHandler

Secure file operations with path validation.

#### Static Methods

##### `validate_path(file_path: str) -> bool`

Validate file path for security (uses `validate_path_secure` internally).

##### `validate_path_secure(file_path: str, allowed_extensions: Optional[Set[str]] = None) -> bool`

Secure path validation with strict directory traversal prevention.

**Parameters**:

- `file_path`: Path to validate
- `allowed_extensions`: Set of allowed extensions (defaults to `{'.docx', '.xlsx'}`)

**Returns**: True if path is valid and safe

##### `open_file_safely(file_path: str) -> bool`

Open file safely (uses `open_file_securely` internally).

##### `open_file_securely(file_path: str) -> bool`

Open file with system default application safely.

**Parameters**:

- `file_path`: Path to file to open

**Returns**: True if file was opened successfully

### WordReader

Word document reading and table extraction.

#### Methods

##### `read_tables_with_headings(file_path: str) -> List[Tuple[pd.DataFrame, Optional[str]]]`

Read tables from Word document and extract associated headings.

**Returns**: List of (table_df, heading) pairs

### AsyncWordReader

Async version of WordReader for improved performance.

#### Constructor

```python
AsyncWordReader(max_workers: int = 4)
```

**Parameters**:

- `max_workers`: Maximum number of worker threads

#### Methods

##### `async read_document_async(file_path: str) -> List[Tuple[pd.DataFrame, Optional[str]]]`

Read Word document asynchronously.

##### `async validate_document_structure_async(file_path: str) -> Dict[str, Any]`

Validate Word document structure asynchronously.

##### `shutdown(wait: bool = True) -> None`

Shutdown the thread pool executor.

### Validators

All validators inherit from `BaseValidator` and implement the `validate()` method.

#### BaseValidator

Abstract base class for all validators.

##### Methods

###### `validate(df: pd.DataFrame, heading: str = None) -> ValidationResult`

Validate a financial statement table (abstract method).

**Returns**: `ValidationResult` with status, marks, and cross-ref marks

#### Available Validators

- `BalanceSheetValidator`: Validates balance sheet statements
- `IncomeStatementValidator`: Validates income statements
- `CashFlowValidator`: Validates cash flow statements
- `EquityValidator`: Validates equity statements
- `TaxValidator`: Validates tax reconciliation tables
- `GenericTableValidator`: Generic validator for other tables

### ValidationResult

Standardized validation result structure.

#### Constructor

```python
ValidationResult(
    status: str,
    marks: List[Dict] = None,
    cross_ref_marks: List[Dict] = None
)
```

**Properties**:

- `status`: Human-readable status message
- `marks`: List of cell marks for formatting
- `cross_ref_marks`: List of cross-reference marks

#### Methods

##### `to_dict() -> Dict[str, Any]`

Convert to dictionary format.

## Exception Classes

### QualityAuditError

Base exception for all Quality Audit errors.

### ValidationError

Raised when validation fails.

### FileProcessingError

Raised when file processing fails.

### SecurityError

Raised when security checks fail.

### ConfigurationError

Raised when configuration is invalid or missing.

### DataFormatError

Raised when data format is invalid or unexpected.

## Usage Examples

### Basic Usage

```python
from quality_audit.services.audit_service import AuditService
from quality_audit.core.cache_manager import AuditContext, LRUCacheManager

# Create context
context = AuditContext(cache=LRUCacheManager(max_size=1000))

# Create service
service = AuditService(context=context)

# Run audit
result = service.audit_document("financial_report.docx", "audit_results.xlsx")

if result['success']:
    print(f"Successfully processed {result['tables_processed']} tables")
else:
    print(f"Error: {result['error']}")
```

### Using Repository Pattern

```python
from quality_audit.core.repositories.financial_data_repository import FinancialDataRepository
from quality_audit.core.cache_manager import LRUCacheManager

cache = LRUCacheManager(max_size=1000)
repo = FinancialDataRepository(cache)

# Save balance sheet data
repo.save_balance_sheet_data("cash", 1000.0, 900.0)

# Retrieve balance sheet data
data = repo.get_balance_sheet_data("cash")
# Returns: (1000.0, 900.0)
```

### Async File Reading

```python
import asyncio
from quality_audit.io.word_reader import AsyncWordReader

async def process_document():
    async with AsyncWordReader(max_workers=4) as reader:
        tables = await reader.read_document_async("document.docx")
        return tables

# Run async function
tables = asyncio.run(process_document())
```

### Custom Validator

```python
from quality_audit.core.validators.base_validator import BaseValidator, ValidationResult
import pandas as pd

class CustomValidator(BaseValidator):
    def validate(self, df: pd.DataFrame, heading: str = None) -> ValidationResult:
        # Custom validation logic
        return ValidationResult(
            status="PASS: Custom validation completed",
            marks=[],
            cross_ref_marks=[]
        )
```
