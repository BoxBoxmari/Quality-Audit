# Audit Codebase – Patterns A–E, Performance, Security, Structure

**Phiên bản:** 1.0  
**Phạm vi:** Ánh xạ patterns false positive A–E, phân tích performance/security/structure  
**Ngày:** 2025-02-06

---

## 1. Pattern Mapping (A–E)

| Pattern | Vị trí code | Root cause | Kịch bản tái hiện |
|--------|-------------|------------|-------------------|
| **A** | `generic_validator.py` lines 75–82 (`_validate_standard_table` Code detection) | F-04: Khi `_detect_code_column(df)` trả về `None`, `df_numeric = df.map(normalize_numeric_column)` normalize toàn bộ cột kể cả Code | Bảng có cột Code tên không chuẩn (vd. "Cột 2") → detection trả None → Code bị normalize → grand total so sánh trên Code |
| **B** | `generic_validator.py` `_validate_column_totals`: `drop_cols` chỉ thêm `code_col` khi `code_col` có giá trị | F-04: Khi `code_col is None`, cột Code không bị drop → tham gia `row_sum` | Cùng điều kiện Pattern A; column-total validation bao gồm cột Code trong tổng |
| **C** | Block boundary trong `_validate_row_totals`, `find_block_sum`, so sánh sum vs total | F-01/F-02: Ranh giới block sai, hoặc cột Code bị loại nhầm, hoặc normalize→NaN | "Tổng chi tiết = 0" trong khi "Tổng trên bảng" > 0: (a) block boundary sai, (b) cột numeric bị coi Code, (c) normalize biến giá trị thành NaN |
| **D** | `generic_validator.py` lines 55–69 (`_should_skip_table`) | F-02: Chỉ kiểm tra `df.iloc[2:]` → bỏ qua dữ liệu numeric ở dòng 0–1 | Bảng có header dòng 0 và dữ liệu số bắt đầu dòng 1 → bị skip vì subset không chứa dòng 0–1 |
| **E** | `tax_validator.py` lines 315–436 (`_validate_remaining_tax_tables`) | F-04: `find_block_sum`, `compare_sum_with_total` và grand total không loại trừ cột Code | Bảng thuế có cột Code (100, 440…) → tổng block và grand total tính cả Code → FAIL "Grand total – Cột 2: 100 vs 440" |

### Root cause F-04 (chi tiết)

- Khi `_detect_code_column(df)` trả về `None`, `df_numeric = df.map(normalize_numeric_column)` normalize **mọi** cột, kể cả Code.
- `find_block_sum`, `compare_sum_with_total`, `_validate_column_totals` chỉ bỏ qua cột Code khi `code_col` có giá trị.
- Hệ quả: Giá trị Code (100, 440…) tham gia vào kiểm tra số học → "Grand total – Cột 2: 100 vs 440".

---

## 2. Extract vs Calculation

- **Extract (đúng):** Dữ liệu được đọc từ Word (WordReader), lưu vào DataFrame. Giá trị trong ô (số, code, text) phản ánh đúng nội dung file.
- **Calculation (nguồn false positive):** Logic validate (normalize, grand-total, block sum, so sánh tổng chi tiết vs tổng trên bảng) dùng toàn bộ cột. Nếu cột Code không bị loại trừ, giá trị code bị coi là số → so sánh vô nghĩa (vd. 100 vs 440).

---

## 3. Priority Actions

1. **F-04 (Pattern A, B, E):** Cứng hóa detection cột Code (fallback heuristic), đảm bảo `df_numeric` và mọi sum/total đều loại trừ cột Code; thống nhất trong `generic_validator` và `tax_validator`.
2. **Pattern C:** Thêm diagnostic logging khi "Tổng chi tiết = 0" nhưng "Tổng trên bảng" > ngưỡng để phân tích sau (block boundary / Code exclusion / normalize→NaN).
3. **Pattern D:** Nới `_should_skip_table`: kiểm tra từ dòng 0 hoặc 1 (adaptive) thay vì chỉ `df.iloc[2:]`.
4. **Performance:** Tối ưu hot path (vectorized `to_numeric`, block slicing, tránh loop nặng).
5. **Security/Structure:** Giữ path validation, docx safety, không log PII; ghi nhận validator consistency (tax "remaining tables" phải dùng cùng chiến lược Code exclusion).

---

## 4. Performance Analysis

- **Hot path:** `df.map(normalize_numeric_column)` áp dụng trên toàn bảng; vòng lặp theo dòng/cột trong `find_block_sum`, `compare_sum_with_total`, `_validate_row_totals`.
- **I/O:** Đọc Word (python-docx), ghi Excel (openpyxl); batch nhiều file tăng I/O.
- **Cơ hội tối ưu:** (1) Vectorized `pd.to_numeric` cho cột numeric thay vì map từng ô; (2) Block slicing thay vì loop từng dòng khi tính block sum; (3) Async/batch khi xử lý nhiều tài liệu (nếu entry point hỗ trợ).

---

## 5. Security Review

- **Path validation:** `FileHandler.validate_path`, `validate_path_secure` – chống traversal, kiểm tra extension và kích thước; gọi trong `AuditService.audit_document` trước khi đọc.
- **Docx safety:** `FileHandler.validate_docx_safety` – zip bomb (ratio, max unzipped size).
- **Input:** Không đưa raw user input vào `eval`/`exec`; đọc file qua python-docx, openpyxl.
- **Subprocess:** Không sử dụng subprocess với input từ file trong luồng validate chính.
- **Logging:** Không ghi PII hoặc secret; tránh log đường dẫn đầy đủ hoặc nội dung file trong production.

---

## 6. Structure & Architecture

- **Luồng module:** config → io → core → services → ui.
- **Vấn đề consistency:** Tax validator nhánh "remaining tables" (`_validate_remaining_tax_tables`) không detect/loại trừ cột Code trong `find_block_sum` và grand total, khác với generic validator đã có `generic_exclude_code_columns` và `_convert_to_numeric_df_excluding_code`. Cần thống nhất: detect Code và loại trừ khỏi mọi sum/total trong tax validator.

---

## 7. Production Spine Fixes (implemented)

- **Column Typing Core:** `quality_audit/utils/column_roles.py` — `infer_column_roles(df, header_row, context)` trả về roles (CODE | LABEL | NUMERIC | OTHER). Mọi sum/total/compare và CY-PY **loại trừ ROLE_CODE**; không còn false FAIL do cộng cột Code.
- **Evidence Gating:** Trước khi validator tính toán, gate với reason NO_EVIDENCE (không đủ cột numeric) hoặc EXTRACT_ERROR (chất lượng extract = 0); output có `gate_decision` và `evidence`.
- **Skip Classifier 2-phase:** `quality_audit/utils/skip_classifier.py` — Phase 1: positive evidence (footer/signature); Phase 2: negative evidence (currency, year, nhãn tài chính). Chỉ SKIP khi phase_1 mạnh và phase_2 yếu; bảng vốn/cổ phần có số không bị SKIP sai.
- **Chi tiết kế hoạch và verification:** `.cursor/plans/production-spine-fixes.md`.

---

*Tài liệu tham chiếu code theo file và hàm; không phụ thuộc số dòng cố định để ổn định giữa các phiên bản.*
