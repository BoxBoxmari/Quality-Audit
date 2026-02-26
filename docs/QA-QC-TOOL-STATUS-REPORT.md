# Báo cáo QA/QC – Hiện trạng công cụ Quality Audit

**Phiên bản tài liệu:** 1.1  
**Phạm vi:** Hiện trạng công cụ sau QA/QC – chuỗi lỗi domino và nguyên nhân gốc rễ  
**Ngày tổng hợp:** 2025-02-05

---

## 0. Feature flags và giá trị mặc định

Các feature flag được định nghĩa trong `quality_audit/config/feature_flags.py` (dict `FEATURE_FLAGS`, hàm `get_feature_flags()`). Giá trị mặc định:

| Flag | Giá trị mặc định | Ý nghĩa |
|------|------------------|---------|
| `heading_fallback_from_table_first_row` | `True` | Bổ sung candidate heading từ dòng đầu bảng khi không có paragraph đủ điểm (giảm nhẹ F-01). |
| `classifier_scan_expansion` | `True` | Mở rộng scan (vd. 60 dòng) và nới điều kiện Balance Sheet (giảm nhẹ F-02). |
| `skip_footer_signature_tables` | `True` | Bỏ qua bảng chữ ký/footer. |
| `generic_exclude_code_columns` | `True` | Nhận diện và loại trừ cột Code khỏi normalize/grand-total (giảm nhẹ F-04). |
| `strict_netting_structure` | `True` | Netting chỉ áp trên cột numeric và ràng buộc block/adjacency (giảm nhẹ F-05). |
| `cashflow_cross_table_context` | `False` | Bật thì dùng registry document-level cho Cash Flow (remediation F-06); **opt-in**, mặc định tắt. |

**Tóm tắt hiện trạng findings:** F-01, F-02, F-04, F-05 đã được **giảm nhẹ** khi các flag tương ứng bật (mặc định bật). F-06 có remediation cross-table nhưng **opt-in** (flag mặc định `False`). F-03 không thay đổi bởi flag.

---

## 1. Tóm tắt điều hành (Executive Summary)

Công cụ Quality Audit hiện đang tạo ra nhiều **FAIL sai logic / vô nghĩa** trên báo cáo tài chính (ví dụ CJCGV, CP Vietnam): Grand total so sánh trên cột Code (100 vs 440), Thiếu code 20 trong Cash Flow dù extract đã có, và netting/grand-total kích hoạt sai trên các bảng statement. Nguyên nhân không phải do số liệu sai mà do **chuỗi thiết kế/implementation** từ bước đọc Word → phân loại bảng → chọn validator → logic validate. Báo cáo này tổng hợp **năm nguyên nhân gốc rễ** đã được kiểm chứng trên codebase và đề xuất **ba nút nghẽn ưu tiên** cần xử lý để giảm false positive nhanh nhất.

---

## 2. Chuỗi lỗi domino (Root Cause Chain)

Quan hệ nhân quả giữa các thành phần:

```
[1] WordReader heading inference yếu / thiếu fallback
        ↓
[2] Nhiều bảng có heading rỗng → table_id = *_unknown
        ↓
[3] TableTypeClassifier: unknown-heuristics quá cứng + scan 20 dòng đầu
        ↓
[4] Balance Sheet / FS tables bị phân loại UNKNOWN
        ↓
[5] ValidatorFactory: UNKNOWN → GenericTableValidator
        ↓
[6] GenericTableValidator: normalize toàn bảng + netting/grand-total quá rộng
        ↓
[7] Cột Code bị coi numeric → FAIL "Grand total - Cột 2: 100 vs 440"; netting false positive
```

Đồng thời:

```
Cash Flow bị tách nhiều bảng (Bảng 6, 7, …)
        ↓
CashFlowValidator chỉ xử lý một bảng (single-table)
        ↓
Bảng 7 không chứa code 20 (nằm ở Bảng 6) → "Thiếu=20"
```

---

## 3. Bảng phát hiện (Findings Matrix)

| ID   | Mức độ  | Khu vực        | File / Vị trí (hàm, class) | Hiện trạng | Mô tả | Nguyên nhân gốc | Khuyến nghị xử lý |
|------|---------|-----------------|-----------------------------|------------|--------|------------------|-------------------|
| F-01 | High    | IO / WordReader | `word_reader.py`: `read_tables_with_headings`, `_derive_heading_from_table_first_row` | **Giảm nhẹ** (flag `heading_fallback_from_table_first_row=True`) | Heading inference không bắt được statement heading khi tiêu đề nằm trong dòng đầu bảng; khi không có paragraph đủ điểm (threshold ≥5) thì giữ heading cũ hoặc rỗng. | Chỉ lấy heading từ 1–8 paragraph **trước** bảng; dòng đầu bảng không được dùng làm candidate. | Bổ sung candidate từ dòng đầu bảng khi không có paragraph đủ điểm; hoặc tách rõ “heading thật” vs “caption trong bảng”. |
| F-02 | High    | Routing         | `table_type_classifier.py`: `scan_rows`, `early_window`, điều kiện BS (`bs_by_early_and_density`, `bs_by_assets_and_liabilities`) | **Giảm nhẹ** (flag `classifier_scan_expansion=True`) | Với heading rỗng/unknown, classifier chỉ quét **20 dòng đầu** và yêu cầu **(assets AND liabilities)** để nhận Balance Sheet. Balance Sheet thực tế có ASSETS ở đầu, LIABILITIES xa phía dưới. | Scan quá nông + điều kiện quá cứng. | Tăng scan (vd. 40–60 dòng) hoặc quét toàn bảng khi heading unknown; nới điều kiện (vd. assets mạnh ở đầu + liabilities xuất hiện bất kỳ đâu). |
| F-03 | High    | Routing / Factory | `factory.py`: `ValidatorFactory.get_validator`, map UNKNOWN → GenericTableValidator | Không đổi | UNKNOWN được map cố định sang GenericTableValidator. | Thiết kế fallback. | Giữ fallback nhưng giảm UNKNOWN bằng cách sửa F-01, F-02; có thể bổ sung “skip unknown” hoặc validator đặc biệt cho unknown. |
| F-04 | Critical| Validators      | `generic_validator.py`: `_validate_standard_table`, `df_numeric`; `base_validator.py`: `_find_total_row`, `_as_numeric_series`, `_detect_total_rows` | **Giảm nhẹ** (flag `generic_exclude_code_columns=True`) | `df.map(normalize_numeric_column)` áp dụng trên **toàn bộ** DataFrame → cột Code (100, 440, …) bị coi là numeric. Grand-total / total-row dùng normalize trên cả row → so sánh trên cột Code → FAIL "Cột 2: 100 vs 440". | Không loại trừ cột Code trước khi normalize và trước khi tính grand-total. | Nhận diện cột Code (tên hoặc pattern) và **không** normalize; grand-total / total-row chỉ áp trên cột numeric. |
| F-05 | High    | Validators      | `generic_validator.py`: `_detect_netting_structure`, logic Total/Less/Net; `base_validator.py`: `_detect_netting_structure`, `_find_total_row` | **Giảm nhẹ** (flag `strict_netting_structure=True`) | Netting kích hoạt nếu **bất kỳ** dòng nào chứa "less"/"net"/…; sau đó áp `Net = Total - Less` cho **mọi cột** (kể cả Code). Trong FS từ "net" xuất hiện rất nhiều (net book value, net cash flows…) → false positive hàng loạt. | Trigger theo keyword quá rộng, không ràng buộc block/adjacency. | Chỉ áp netting trên **cột numeric**; và/hoặc yêu cầu total/less/net nằm trong cùng block (cách nhau vài dòng / cùng section). |
| F-06 | High    | Validators      | `cash_flow_validator.py`: build `data` từ `tmp.iterrows()`, `check("50", ["20","30","40"])`; nhánh dùng `context.cash_flow_registry` | **Remediation opt-in** (flag `cashflow_cross_table_context=False`) | `data` (code → value) được build từ **một bảng duy nhất**. Rule check("50", ["20","30","40"]) chạy trên bảng hiện tại. Nếu Cash Flow tách nhiều bảng (Bảng 6: operating/code 20, Bảng 7: investing/code 30), validate Bảng 7 → không có "20" trong `data` → "Thiếu=20". | Thiết kế single-table, không có cross-table registry. | Bật `cashflow_cross_table_context=True` để dùng registry document-level; AuditService build registry trước, CashFlowValidator đọc từ context. |

### 3b. Luồng build cash_flow_registry khi cashflow_cross_table_context=True

Khi flag `cashflow_cross_table_context=True`:

1. **AuditService._validate_tables**: Pass 1 duyệt tất cả bảng, gọi `ValidatorFactory.get_validator`; thu thập bảng là `CashFlowValidator` vào `cf_tables`. Gọi `_build_cf_registry(cf_tables)` → `full_registry` (dict code → (current_year, prior_year) từ mọi bảng CF). Gán `context.cash_flow_registry = full_registry`.
2. Vòng lặp validate từng bảng: khi tới bảng Cash Flow, `CashFlowValidator.validate` đọc `context.cash_flow_registry` đã được set → dùng dữ liệu cross-table.
3. Sau vòng lặp: restore `context.cash_flow_registry = orig_registry`.

**Lưu ý:** Trong `CashFlowValidator`, nhánh “Backward-compatible sequential merge” khi flag bật nhưng `context.cash_flow_registry` là `None` gọi `registry.get(...)` trên `None` → lỗi. Luồng chuẩn qua `AuditService` luôn set registry trước khi validate bảng CF; lỗi chỉ xảy ra nếu gọi `CashFlowValidator` độc lập (vd. test đơn lẻ) với context chưa set registry. Khuyến nghị: khởi tạo `registry = {}` trong nhánh else hoặc kiểm tra `registry is not None` trước khi dùng.

---

## 4. Kiểm chứng từng phát hiện (Verification Summary)

### 4.1. FAIL "Grand total - Cột 2: 100 vs 440" có phải do tính trên cột Code?

**Kết luận: Đúng.**  
Trong FS casting CJCGV, Bảng 2 có cột Code với giá trị 100 (Current assets), 440 (Total resources). Focus List báo "Grand total - Cột 2: Tổng cộng=100, Dòng cuối=440". Cột 2 chính là cột Code. `generic_validator.py`: trong `_validate_standard_table`, `df_numeric = df.map(normalize_numeric_column)`; `base_validator._find_total_row` dùng `_as_numeric_series(row)` = `row.map(normalize_numeric_column)`. Do đó cột Code bị coi numeric và tham gia so sánh grand-total.

### 4.2. Balance Sheet bị route sai sang Generic vì classifier quét 20 dòng không thấy "liabilities"?

**Kết luận: Đúng.**  
`table_type_classifier.py`: biến `scan_rows = min(20, total_rows)` (early_window); khi heading rỗng/unknown, Balance Sheet chỉ được chọn nếu `(has_keywords["assets"] and has_keywords["liabilities"]) and code_density > 0.3` (logic `bs_by_early_and_density`, `bs_by_assets_and_liabilities`). Trong nhiều mẫu, LIABILITIES nằm xa hơn 20 dòng → UNKNOWN → Factory trả GenericTableValidator.

### 4.3. "Thiếu=20" có phải do Cash Flow tách nhiều bảng và CashFlowValidator single-table?

**Kết luận: Đúng.**  
Trong CJCGV, Bảng 6 chứa code 20 (operating), Bảng 7 chứa code 30 (investing). `cash_flow_validator.py`: build `data` từ `tmp.iterrows()` của table hiện tại trong vòng lặp chuẩn bị `data`; gọi `check("50", ["20","30","40"])`. Nếu validate từng bảng và bảng hiện tại là Bảng 7 thì `data` không có "20" → báo thiếu 20, dù extract toàn file đã có code 20 ở Bảng 6.

### 4.4. Netting/grand-total FAIL hàng loạt do trigger keyword quá rộng?

**Kết luận: Đúng.**  
`generic_validator.py`: trong block netting (`_detect_netting_structure`, logic Total/Less/Net), chỉ cần một dòng bất kỳ chứa "less"/"net"/… thì `has_netting=True`; áp `Net = Total - Less` cho mọi cột, không giới hạn block hay cột numeric. Trong báo cáo tài chính từ "net" xuất hiện rất nhiều → false positive.

---

## 5. Kế hoạch xử lý (Remediation Plan)

### 5.1. Ưu tiên 1 – Giảm FAIL nhanh (short-term)

| Thứ tự | Nút nghẽn | Hành động đề xuất | Owner / Ghi chú |
|--------|-----------|-------------------|------------------|
| (i)    | Heading rỗng / thiếu fallback trong WordReader | Bổ sung candidate heading từ dòng đầu bảng khi không có paragraph đủ điểm; hoặc tách logic “heading ngoài bảng” vs “caption trong bảng”. | Cần test với CJCGV, CP Vietnam để đảm bảo không tạo heading sai. |
| (ii)   | Unknown-heuristics: scan 20 dòng + assets∧liabilities | Tăng `scan_rows` (vd. 40–60) hoặc quét toàn bảng khi heading unknown; nới điều kiện Balance Sheet (vd. assets ở đầu + liabilities xuất hiện bất kỳ đâu trong bảng). | Cân nhắc performance khi bảng rất dài. |
| (iii)  | Generic: Code bị coi numeric + netting/grand-total quá rộng | Nhận diện cột Code (tên cột hoặc pattern) và loại trừ khỏi normalize và khỏi grand-total/total-row; chỉ áp netting trên cột numeric; thu hẹp trigger netting (block/adjacency hoặc whitelist context). | Có thể bổ sung cấu hình “numeric_columns” / “exclude_columns” cho từng loại bảng. |

### 5.2. Ưu tiên 2 – Thiết kế (medium-term)

| Hạng mục | Mô tả |
|----------|--------|
| CashFlow cross-table | Thiết kế cơ chế cho CashFlowValidator nhận nhiều bảng (hoặc context document-level), build `data` từ toàn bộ cash flow tables trước khi check("50", ["20","30","40"]). |
| Cải thiện classification | Sau khi có heading tốt hơn (F-01), đánh giá lại tỷ lệ UNKNOWN; nếu cần, bổ sung heuristic theo từng loại FS (VN/IFRS, template CJCGV, CP Vietnam). |

### 5.3. Kiểm tra sau khi sửa (Verification Commands)

- Chạy tool trên cùng bộ input (CJCGV, CP Vietnam) và so sánh:
  - Số lượng bảng `*_unknown` (kỳ vọng giảm).
  - Số FAIL "Grand total - Cột X" khi Cột X là Code (kỳ vọng = 0).
  - Số FAIL "Thiếu=20" cho Cash Flow khi code 20 có trong extract (kỳ vọng = 0 sau khi có cross-table).
  - Số netting/grand-total FAIL vô nghĩa (giảm mạnh sau khi thu hẹp trigger và loại trừ cột Code).

---

## 5b. Audit Codebase (Patterns A–E, Performance, Security, Structure)

Tài liệu chi tiết: [docs/AUDIT-CODEBASE-PERFORMANCE-SECURITY-STRUCTURE.md](AUDIT-CODEBASE-PERFORMANCE-SECURITY-STRUCTURE.md).

### Tóm tắt findings

- **A–B, E:** Cột Code không bị loại trừ khi `code_col` là `None` (F-04); trong `tax_validator._validate_remaining_tax_tables` không có Code exclusion.
- **C:** "Tổng chi tiết = 0" do lỗi ranh giới block, loại trừ Code sai, hoặc normalize→NaN.
- **D:** `_should_skip_table` chỉ kiểm tra `df.iloc[2:]`, bỏ qua dữ liệu numeric ở dòng 0–1.

Phân tích performance, security và structure tham chiếu trong file audit trên.

---

## 6. Tài liệu tham chiếu

- `quality_audit/io/word_reader.py` – heading inference, gán heading cho bảng.
- `quality_audit/core/routing/table_type_classifier.py` – phân loại bảng, điều kiện Balance Sheet/unknown.
- `quality_audit/core/validators/factory.py` – map UNKNOWN → GenericTableValidator.
- `quality_audit/core/validators/generic_validator.py` – normalize toàn bảng, netting, grand-total.
- `quality_audit/core/validators/base_validator.py` – `_find_total_row`, `_as_numeric_series`.
- `quality_audit/core/validators/cash_flow_validator.py` – build `data` từ một bảng, check 20/30/40/50.
- `docs/ARCHITECTURE.md` – kiến trúc tổng thể.
- `docs/AUDIT-CODEBASE-PERFORMANCE-SECURITY-STRUCTURE.md` – audit patterns A–E, performance, security, structure.

---

*Báo cáo này tổng hợp từ kết quả QA/QC và thảo luận về chuỗi lỗi domino. Tham chiếu code theo tên hàm/class (không dùng số dòng) để ổn định giữa các phiên bản.*
