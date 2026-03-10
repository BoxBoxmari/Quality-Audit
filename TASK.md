# TASK: Production readiness — chốt sổ deploy

## Context

Quality Audit Tool chuẩn bị production. Cần: test sạch, dọn file rác, tái cấu trúc file lẻ vào folder, cập nhật/xóa docs và scripts không dùng. Mục tiêu: repo sạch, cấu trúc rõ ràng, docs và scripts đồng bộ với hiện trạng.

## Requirements

- [x] Chạy full test Python và sửa hết lỗi (pytest).
- [x] Dọn toàn bộ file rác, testing/debug/dump không còn giá trị và không dùng nữa (root + scripts nếu có).
- [x] Tái cấu trúc file riêng lẻ ở root vào folder (scripts / docs / tests) theo chuẩn dự án.
- [x] Cập nhật tất cả Docs và Scripts cần thiết; xóa tài liệu/script không còn dùng.

## Verification Commands

- `pytest tests/ -v`
- `ruff check quality_audit scripts`
- (Sau dọn) Không còn file debug/dump/tmp ở root; script chạy được từ `scripts/` nếu có entry point.

## Exit Criteria

Bốn requirement trên đều đạt; pytest và ruff pass; repo sạch, cấu trúc rõ, docs/scripts đồng bộ. Trạng thái production-ready.
