# Chính sách baseline và hồi quy (Legacy Parity)

Tài liệu này cố định cách lấy baseline, chạy hồi quy hai tài liệu DOCX và so sánh kết quả trong bối cảnh **legacy parity**. Nó bổ sung (không thay thế) các hợp đồng trong `docs/PARITY_CONTRACT.md` và ma trận trong `docs/PARITY_SUPPORTED_MATRIX.md`.

## Tham chiếu bắt buộc

| Nguồn | Vai trò |
|--------|---------|
| `docs/PARITY_CONTRACT.md` | Định nghĩa hành vi runtime khi `legacy_parity_mode=True` (định tuyến validator, không chạy Big4 primary/shadow, v.v.). |
| `docs/PARITY_SUPPORTED_MATRIX.md` | Trạng thái LOCKED/PARTIAL/OUT_OF_SCOPE và bài test khóa tương ứng. |
| `legacy/main.py`, `legacy/Quality Audit.py` | Nguồn ngữ nghĩa tham chiếu cho parity (đọc song song khi tranh luận về “đúng theo legacy”). |
| `quality_audit/core/parity/legacy_baseline.py` | Khóa cache / combined keys bám legacy cho cross-check. |
| `docs/TASK.md` | Ngữ cảnh pipeline 2 DOCX, lệnh xác minh mẫu và ghi chú fixture. |

## Cờ parity và authority runtime

- Định nghĩa mặc định hiện tại trong `quality_audit/config/feature_flags.py`:
  - `baseline_authoritative_default=False`
  - `legacy_bug_compatibility_mode=False`
  - `legacy_parity_mode=False`
- Luồng runtime phải đọc cờ qua `get_feature_flags()` (không đọc trực tiếp `FEATURE_FLAGS` cho hành vi audit).
- `get_feature_flags()` hợp nhất alias tương thích:
  - `legacy_bug_mode = legacy_bug_compatibility_mode OR legacy_parity_mode`
  - sau đó ghi ngược cả hai key về cùng giá trị hiệu lực này.
- Khi `legacy_bug_mode` hiệu lực, hàm sẽ ép `False` cho nhóm cờ trong `_PARITY_FORCED_FALSE_WHEN_LEGACY_PARITY` (Big4/gating/non-legacy helpers) để giữ đường chạy parity ổn định.

### Ma trận cờ -> `use_legacy_as_authority`

Điều kiện trong `quality_audit/services/audit_service.py::_validate_single_table`:

`use_legacy_as_authority = baseline_authoritative_default and (legacy_bug_compatibility_mode or legacy_parity_mode)`

| `baseline_authoritative_default` | `legacy_bug_compatibility_mode` | `legacy_parity_mode` | `use_legacy_as_authority` |
|---|---|---|---|
| False | False | False | False |
| False | True | False | False |
| False | False | True | False |
| True | False | False | False |
| True | True | False | True |
| True | False | True | True |
| True | True | True | True |

Ý nghĩa vận hành:
- Mặc định production hiện tại đi theo đường validator/classifier hiện đại (không legacy-authoritative).
- Legacy authority chỉ bật khi có chủ đích (baseline default + một cờ compatibility/parity).
- Khóa hành vi: `tests/test_parity_runtime_routing.py`, `tests/test_feature_flags_parity_force.py`, `tests/test_audit_service_legacy_engine_default.py`.

## Pipeline baseline / hồi quy (2 DOCX)

Luồng chuẩn (theo `docs/TASK.md` và `scripts/run_regression_2docs.py`):

1. **Đầu vào:** hai tệp DOCX (thường CP Vietnam và CJCGV như trong Context của TASK).
2. **Chạy:** `python scripts/run_regression_2docs.py …`  
   - Ghi XLSX theo `--output-dir`, báo cáo markdown theo `--report-name`, tiền tố tên file theo `--prefix`.  
   - Mặc định: `--report-name baseline_2docs.md`, `--prefix baseline`, thư mục đầu ra `reports/`.  
   - Nếu **không** truyền đường dẫn DOCX, script dùng `resolve_default_doc_paths(root)`: thứ tự thư mục dưới root là **`data/` → `tests/test_data/` → `tests/data/` → `test_data/`**. Cả hai file phải nằm trong **cùng** một thư mục đó. Tên: **CP** — `CP Vietnam-FS2018-Consol-EN.docx` (hoặc cùng stem, `.docx` không phân biệt hoa thường); **CJCGV** — ưu tiên `CJCGV-FS2018-EN- v2.docx`, sau đó `CJCGV-FS2018-EN- v2 .docx`, có thể quét thư mục nếu không khớp đường dẫn chính xác.
3. **Tổng hợp:** trừ khi `--no-aggregate`, script gọi `scripts/aggregate_failures.py` trên các XLSX đầu ra → `reports/aggregate_failures.csv` và `reports/aggregate_failures.json` (đường dẫn thực tế theo cấu hình script khi chạy).

`AuditContext` trong script dùng `TaxRateConfig` cố định (headless, không `input()`), phù hợp CI/local không tương tác.

## Fixture DOCX và clone sạch

- Repo thường **không** chứa hai DOCX mẫu: `.gitignore` loại `*.docx` và thư mục `data/` theo mô tả trong `docs/TASK.md`.
- Để chạy E2E đầy đủ: người vận hành đặt **cả hai** DOCX vào **một** thư mục trong chuỗi ưu tiên (`data/` trước, rồi `tests/test_data/`, `tests/data/`, `test_data/`) — khớp `resolve_default_doc_paths` / `_default_doc_paths()` — hoặc truyền đường dẫn tuyệt đối qua CLI.
- Thiếu fixture: pipeline vẫn có thể “chạy” nhưng sẽ báo không tìm thấy file hoặc không hoàn tất audit — **không** coi là pass hồi quy E2E.
- Preflight khuyến nghị trước khi chạy regression:
  - `python scripts/check_regression_fixtures.py --strict`
  - Exit `0`: đã có đủ cặp fixture mặc định.
  - Exit `2`: thiếu fixture mặc định (cần provision DOCX hoặc truyền đường dẫn explicit).

### Decision Record: Fixture strategy

- **Decision (2026-03-23):** dùng chiến lược **local-only fixtures**.
- **Why now:** giữ repo nhẹ, tránh lưu binary nhạy cảm/khó governance trong nguồn chính.
- **Impact:** E2E regression phụ thuộc provision fixture cục bộ; preflight strict là cổng bắt buộc trước khi chạy baseline/after.
- **Rollback/alternative:** nếu cần reproducibility CI mạnh hơn, có thể chuyển sang artifact strategy (remote fixture + checksum contract) trong một PR policy riêng.

## Tiêu chí so sánh baseline

So sánh **ưu tiên** theo tổng hợp aggregate (ổn định, dễ diff):

- Đọc `aggregate_failures.json`: các trường như `group_count`, `total_fail_warn_rows` và phân nhóm theo loại lỗi/cảnh báo (theo schema file thực tế sau mỗi lần chạy).
- So khớp **xu hướng** và **ngưỡng** đã ghi trong `docs/TASK.md` (ví dụ các nhóm COLUMN_TOTAL_VALIDATION, EQUITY_FORMULA_CHECK, v.v.) khi có baseline “last run” được team chấp nhận.
- So sánh thứ cấp: diff có chọn lọc trên XLSX hoặc báo cáo markdown (`baseline_2docs.md` vs `after_2docs.md`) khi cần điều tra chi tiết từng bảng.

**Nguyên tắc:** Thay đổi làm **tăng** số nhóm logic (FAIL/WARN) liên quan parity trong khi không có lý do được ghi trong TASK/contract → cần review. Giảm nhờ sửa lỗi logic có test khóa → chấp nhận sau khi pytest parity liên quan xanh.

## Ranh giới: trong parity vs ngoài phạm vi

**Trong phạm vi parity (theo contract + matrix):** định tuyến validator, cache cross-table, chọn total-row / cột amount quan trọng, alias AR/AP, tax columns, FORM_1 total row — các hạng mục có test LOCKED.

**Ngoài phạm vi parity (ghi nhận, không dùng để “fail” baseline trừ khi team mở rộng contract):**

- Khác biệt trích xuất ở mức fidelity/format phụ thuộc binary toolchain hoặc môi trường OCR (ngoài các contract deterministic đã khóa bằng test).
- Metadata quan sát không chặn (non-blocking observability).

Chi tiết OUT_OF_SCOPE: `docs/PARITY_CONTRACT.md` (mục Out of scope) và cột OUT_OF_SCOPE trong `docs/PARITY_SUPPORTED_MATRIX.md`.

## Lệnh tham chiếu (PowerShell)

Theo `docs/TASK.md`:

```powershell
cd "c:\Users\Admin\Downloads\Quality Audit Tool"
python scripts/check_regression_fixtures.py --strict
python scripts/run_regression_2docs.py "data/CP Vietnam-FS2018-Consol-EN.docx" "data/CJCGV-FS2018-EN- v2 .DOCX" --output-dir reports --report-name after_2docs.md --prefix after
python -c "import json; d=json.load(open('reports/aggregate_failures.json')); print('groups', d['group_count'], 'fail_warn', d['total_fail_warn_rows'])"
pytest tests/test_parity_runtime_routing.py -q --tb=short
```

Điều chỉnh đường dẫn DOCX và tên báo cáo/tiền tố cho lần chạy baseline so với candidate.

## Môi trường (encoding)

Trên Windows, console mã `cp1252` có thể gây `UnicodeEncodeError` khi in ký tự ngoài BMP. Đây là vấn đề **môi trường** (UTF-8 console / `chcp 65001`), không phải tiêu chí pass/fail của logic parity.

## Thay đổi chính sách

Mọi thay đổi làm lệch hành vi đã LOCKED phải kèm: cập nhật test parity, ghi rõ lý do trong PR, và cập nhật `PARITY_CONTRACT.md` / ma trận nếu phạm vi contract thay đổi.
