# Remediation: Phát hiện đối chiếu cell-level (Input .docx vs Output _output.xlsx)

Tài liệu ánh xạ **bằng chứng đối chiếu ô dữ liệu** (user) vào **vị trí code** và **hướng sửa** cụ thể.

---

## 1. Tổng quan hai nhóm vấn đề

| Nhóm | Mô tả | Rủi ro |
|------|--------|--------|
| **Trích xuất sai/mất cột** | Mất cột amount, mất cột năm (PY/2017), duplicated period headers làm rơi cột cuối, "%" không coi là numeric | Output không phản ánh input; nhiều bảng WARN/INFO nhưng dữ liệu sai |
| **Validator false fail/warn** | Chọn nhầm cột (Total vs thành phần), áp sai rule (statement sum-to-total), bỏ sót dòng đầu khi cộng, logic equity roll-forward sai | FAIL không đúng; mất niềm tin vào tool |

---

## 2. Trích xuất (Extraction)

### 2.1 Mất cột amount (tbl_006 Cash flow, tbl_004 CP Vietnam Cash flow)

- **Triệu chứng:** Output chỉ còn code (1,2,3…), mất toàn bộ cột amount.
- **Vị trí code cần kiểm tra:**
  - `quality_audit/io/word_reader.py` – reconstruct table, multi-row header, cột được gán từ OOXML.
  - `quality_audit/io/extractors/ooxml_table_grid_extractor.py` (hoặc extractor đang dùng) – grid/merge, mapping cột.
- **Hướng sửa:** Đảm bảo sau khi detect header (multi-row), **mọi cột có số trong input** đều có cột tương ứng trong DataFrame; không loại bỏ cột “amount” vì nhầm với label/code.

### 2.2 Mất cột năm (PY hoặc 2017) khi có duplicated period headers

- **Triệu chứng:** tbl_009 (mất 1/1/2018), tbl_026 (mất 1/1/2018), tbl_050 (mất 2017). Input có 2 cột cùng tên (31/12/2018, 31/12/2018, 1/1/2018) → output chỉ giữ 31/12/2018 (lặp), mất cột cuối.
- **Vị trí code:** Header dedup / unique column name – chỗ nào ép `columns` thành unique (vd. rename duplicate) mà **xóa hoặc gộp nhầm cột năm**.
- **Hướng sửa:** Khi có **duplicated period headers**, không xóa cột dữ liệu. Dùng suffix (vd. `_CY`, `_PY`, `_1`, `_2`) để giữ đủ cột; map lại CY/PY theo vị trí hoặc theo nội dung ô (năm) chứ không chỉ theo tên cột trùng.

### 2.3 Cột "%" không được coi là numeric (tbl_005 % equity, FAIL_TOOL_EXTRACT)

- **Triệu chứng:** Bảng có "100% / 49%" nhưng báo "No numeric columns".
- **Vị trí code:**
  - `quality_audit/utils/numeric_utils.py` – `normalize_numeric_column`: chuỗi có "%" cần được strip "%" rồi parse số.
  - `quality_audit/utils/column_roles.py` – `infer_column_roles`: header_hint "percent" đã có; cần đảm bảo **numeric_density** của cột "%" được tính đúng (parse "100%" → 100.0).
- **Hướng sửa:** Trong `normalize_numeric_column`, trước khi `pd.to_numeric`, strip "%" và chia 100 nếu cần (hoặc giữ nguyên 100); đảm bảo cột chỉ chứa giá trị dạng "X%" có density đủ để được gán ROLE_NUMERIC.

### 2.4 Bảng thiếu trong output (CJCGV 48 → 43, thiếu bảng #31 % equity)

- **Triệu chứng:** 4 table footer signature (bỏ qua là đúng); 1 table #31 (cơ cấu sở hữu / % equity) có nội dung nhưng không xuất hiện trong output.
- **Vị trí code:**
  - `quality_audit/services/audit_service.py` – chỗ gọi `classify_footer_signature` và skip table; điều kiện skip khi "insufficient numeric evidence".
  - `quality_audit/utils/skip_classifier.py` – 2-phase classifier: footer vs financial.
- **Hướng sửa:** Bảng chỉ có cột "%" không được coi là "no numeric evidence" sau khi đã sửa 2.3. Nếu bảng % equity vẫn bị skip, bổ sung rule: bảng có heading chứa "equity owned" / "voting rights" / "cơ cấu sở hữu" và có ít nhất một cột parse được số (kể cả %) → không skip.

---

## 3. Validator – Chọn cột và vùng cộng

### 3.1 Fixed asset (tbl_017): BSPL so với cột “Office fixtures” thay vì cột “Total”

- **Triệu chứng:** Note có Closing balance total = 2,308,571,151; validator so BSPL 2,308,571,151 với Note 17,295,538 (đó là cột Office fixtures). Log: chosen_numeric_columns = ['1','2','3','4','5'], **loại cột Total**.
- **Vị trí code:**
  - `quality_audit/utils/column_roles.py` – cột header "Total" có thể bị gán ROLE_OTHER/LABEL thay vì NUMERIC.
  - `quality_audit/core/validators/generic_validator.py` – `_validate_fixed_assets`: dùng `ColumnDetector.detect_financial_columns_advanced(df)` để lấy CY/PY **column name**; nếu chỉ dùng “last two numeric” thì sẽ lấy 2 cột thành phần thay vì Total.
- **Hướng sửa:** Trong fixed-asset BSPL cross-check, **ưu tiên cột có header chứa "total"/"tổng"** (sau khi normalize) làm cột so sánh với BSPL. Chỉ fallback sang last-two numeric khi không tìm thấy cột Total. Đồng thời: trong `column_roles`, cột header "Total"/"Tổng" mà có numeric_density đủ cao → ROLE_NUMERIC để không bị loại khỏi chosen_numeric_columns.

### 3.2 Income statement (tbl_004): Rule “column total” không phù hợp bảng có nhiều subtotal

- **Triệu chứng:** Validator kiểm "tổng chi tiết = tổng trên bảng" nhưng 18,428,002 là một dòng subtotal, không phải grand total → false fail.
- **Vị trí code:** `quality_audit/core/validators/income_statement_validator.py` và/hoặc `generic_validator.py` – chỗ áp **column total validation** cho bảng income statement.
- **Hướng sửa:** Phân biệt **statement (nhiều subtotal)** vs **note (một total cuối)**. Với statement: chỉ so “sum of details” với **dòng grand total** (vd. "Profit after tax", "Total comprehensive income"), không so với từng subtotal; hoặc tắt rule sum-to-total cho bảng có >1 dòng total-like.

### 3.3 Bỏ sót dòng đầu khi cộng chi tiết (tbl_021, tbl_022, tbl_014, tbl_037)

- **Triệu chứng:** Sai lệch đúng bằng giá trị **dòng chi tiết đầu tiên** (vd. Warner Bros 1,380,735; CJ CGV 9,490,365; Goods in transit 1,111,303,413,550; USD 12,490,746,774).
- **Vị trí code:**
  - `quality_audit/core/validators/generic_validator.py`:
    - **find_block_sum(start_idx)** (khoảng 1490–1507): bắt đầu từ `i = start_idx + 1`. Nếu `start_idx` được set = 0 vì coi **row 0 là “empty”** (theo `all(str(cell).strip() == "" for cell in row)` với `df.iloc[i]`), thì dòng 0 bị bỏ qua.
    - **Leading empty detection** (1436–1442): `start_idx = -1`; với mỗi row 0..4, nếu row **all empty** thì `start_idx = i`, else break. Nếu row 0 có **một ô trống** (vd. code) và các ô còn lại là số, row 0 không all-empty → start_idx = -1 → sum từ 0. Bug xảy ra khi: (1) row 0 trong **df** bị export/parse thành toàn empty (merge cell, lỗi extract), hoặc (2) logic “empty” đang dùng **df** thay vì **df_numeric** nên có row toàn NaN/empty trong df nhưng có số trong df_numeric.
- **Hướng sửa:** Khi xác định “leading empty” cho **find_block_sum**, không coi một row là empty nếu **có ít nhất một giá trị numeric** trong các cột amount (hoặc trong df_numeric). Ví dụ: thay điều kiện `all(str(cell).strip() == "" for cell in row)` bằng: “row là empty chỉ khi không có bất kỳ ô nào trong row có numeric (sau normalize_numeric_column) trong các cột không phải code”. Hoặc: dùng `df_numeric` để quyết định row có data hay không (có bất kỳ ô nào không NaN trong amount_cols).

### 3.4 Equity (tbl_030): Logic roll-forward sai – “Balance at 1 Jan” = movement thay vì Opening + movement

- **Triệu chứng:** Bảng roll-forward đúng (Opening + movement = Closing), nhưng validator tính sai kiểu "Balance at 1 Jan 2018" = chỉ movement (106,223,262) thay vì Opening + movement.
- **Vị trí code:** `quality_audit/core/validators/equity_validator.py` – chỗ tính **expected** cho dòng "Balance at 1 Jan" / "Balance at 31 Dec". Cần kiểm tra: expected có đang = previous balance + movement cho đúng dòng “Balance at end” không, và “Balance at beginning” có đang = previous period closing không.
- **Hướng sửa:** Rà lại công thức expected: (1) Dòng "Balance at beginning of period" → expected = closing balance của kỳ trước (hoặc opening đã lưu). (2) Dòng "Balance at end of period" → expected = opening + movement (tổng các dòng movement). Đảm bảo không nhầm cột/dòng (movement vs balance).

---

## 4. Mức độ báo lỗi (Severity / visibility)

- **Vấn đề:** Nhiều bảng **mất cột năm** nhưng status chỉ WARN/INFO → dễ bỏ qua khi review.
- **Vị trí code:** Nơi gán status_enum (PASS/FAIL/WARN/INFO) khi **không có total row** hoặc **không đủ numeric columns** – có thể trong generic_validator (evidence gate) hoặc audit_service.
- **Hướng sửa:** Khi phát hiện **thiếu cột so với kỳ vọng** (vd. chỉ có 1 cột năm thay vì 2, hoặc so sánh với header input), nên nâng lên **WARN hoặc FAIL** (vd. FAIL_TOOL_EXTRACT hoặc WARN_MISSING_PERIOD_COLUMN) thay vì INFO, để không lọt review.

---

## 5. Checklist triển khai (gợi ý thứ tự)

1. **numeric_utils + column_roles:** Parse "%" và gán ROLE_NUMERIC cho cột % (2.3).
2. **column_roles:** Cột "Total"/"Tổng" có numeric_density đủ → NUMERIC; **generic_validator _validate_fixed_assets:** Ưu tiên cột Total cho BSPL (3.1).
3. **generic_validator find_block_sum / leading empty:** Không coi row là empty nếu có numeric trong amount cols / df_numeric (3.3).
4. **income_statement / generic:** Phân biệt statement vs note; tránh so sum với subtotal (3.2).
5. **equity_validator:** Sửa expected cho Balance at beginning/end (3.4).
6. **Extraction (word_reader + extractors):** Giữ đủ cột amount; xử lý duplicated period headers không làm mất cột năm (2.1, 2.2).
7. **skip_classifier / audit_service:** Không skip bảng % equity khi đã có numeric (2.4).
8. **Severity:** Nâng mức báo khi mất cột kỳ (2.2, 4).

---

## 6. Tham chiếu file chính

| File | Liên quan |
|------|-----------|
| `quality_audit/utils/numeric_utils.py` | normalize_numeric_column, "%" (2.3) |
| `quality_audit/utils/column_roles.py` | Total = NUMERIC, "%" density, chosen_numeric (2.3, 3.1) |
| `quality_audit/core/validators/generic_validator.py` | find_block_sum, start_idx, leading empty (3.3); fixed-asset CY/PY, BSPL (3.1); column total rule (3.2) |
| `quality_audit/core/validators/equity_validator.py` | Balance at begin/end expected (3.4) |
| `quality_audit/core/validators/income_statement_validator.py` | Rule sum-to-total cho statement (3.2) |
| `quality_audit/io/word_reader.py` | Reconstruct table, header, cột (2.1, 2.2) |
| `quality_audit/io/extractors/*` | Grid/merge, cột (2.1, 2.2) |
| `quality_audit/services/audit_service.py` | Skip table, numeric evidence (2.4, 4) |
| `quality_audit/utils/skip_classifier.py` | Footer vs financial (2.4) |
