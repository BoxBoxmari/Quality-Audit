# Ticket: Fix openpyxl DeprecationWarning (font.copy)

**ID:** TICKET-OPENPYXL-DEPRECATION  
**Status:** Done  
**Scope:** `quality_audit/io/excel_writer.py`

## Mô tả

DeprecationWarning do dùng `font.copy(...)` trong `quality_audit/io/excel_writer.py`. openpyxl đã deprecated StyleProxy `.copy(**kw)`; khuyến nghị tạo Font mới từ thuộc tính hiện tại cộng overrides.

## Nguyên nhân

- Nhiều chỗ gọi `cell.font = cell.font.copy(bold=True)` hoặc `cell.font.copy(bold=True, size=16)`.
- openpyxl khuyến nghị dùng `copy.copy(obj)` hoặc tạo instance Font mới thay vì `.copy(**kw)`.

## Giải pháp

- Thêm helper `_font_with(font, **overrides)` trong `excel_writer.py`: đọc thuộc tính hiện tại của font (name, size, bold, italic, color, …), merge với overrides, tạo `Font(**merged)` và return.
- Thay tất cả `cell.font = cell.font.copy(...)` bằng `cell.font = _font_with(cell.font, ...)`.

## Tiêu chí hoàn thành

- [x] Chạy `pytest` / gọi ExcelWriter với `warnings.filterwarnings('error', category=DeprecationWarning, module='openpyxl')` — không còn DeprecationWarning openpyxl.
- [x] Hành vi xuất Excel không đổi (dùng `_font_with(font, **overrides)` thay `font.copy(**overrides)`; output Font giống nhau).

## Ghi chú

- Font constructor openpyxl chấp nhận: name, size, bold, italic, underline, strike, color, outline, shadow, condense, extend, vertAlign, charset, family, scheme.
- Helper dùng getattr để tương thích cả Font và StyleProxy.
