# OpenMemory Guide

## Overview

Quality Audit Tool (Python) có bug “repeated-run inconsistency” khi chạy phân tích nhiều lần trong cùng process/app session do rò rỉ state giữa các lần chạy.

## Patterns

- **Run-scoped state reset**: Mỗi lần gọi entrypoint audit phải reset toàn bộ state có thể ảnh hưởng output: `AuditContext` (marks/metadata) và cache cross-check (global + legacy + context).
- **State ownership**: Ưu tiên `AuditContext.cache`/`AuditContext.marks` làm owner run-scoped; chỉ fallback về globals để tương thích backward.
- **Legacy globals**: `legacy/main.py` giữ `BSPL_cross_check_cache` và `BSPL_cross_check_mark` cần được clear ở boundary mỗi run nếu legacy path được load trong cùng process.

## Components

- `quality_audit/services/audit_service.py`: `_reset_run_state()` là điểm “run boundary” để clear:
  - `self.context.clear()` và `self.context.cache.clear()`
  - `cross_check_cache.clear()` và `cross_check_marks.clear()`
  - `legacy_main.BSPL_cross_check_cache.clear()` và `legacy_main.BSPL_cross_check_mark.clear()` (khi module legacy được load)
- `quality_audit/core/validators/base_validator.py`: helper `_active_cross_check_cache()` và `_active_cross_check_marks()` để ưu tiên context trước globals.
- `quality_audit/services/financial_reconciliation_service.py`: ưu tiên `AuditContext.cache` khi reconcile.

## Tests

- `tests/test_audit_service_integration.py`:
  - `test_repeated_sync_runs_reset_legacy_and_global_state`
  - `test_repeated_async_runs_reset_state`
- `tests/test_financial_reconciliation_service_context.py`:
  - `test_reconciliation_prefers_context_cache_over_global`