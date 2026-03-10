## Project notes (agent-maintained)

### NOTE validation routing (deny-by-default)

- `AuditGradeValidator` tách `BASIC_NUMERIC_CHECKS` thành fallback và **không** dùng “no real evidence” để kích hoạt fallback cho `GENERIC_NOTE`/`TAX_NOTE`. Điều này tránh false FAIL/WARN do heuristic total-row/scope.
- `HIERARCHICAL_NETTING` được thực thi bởi rule chuyên biệt `NETTING_BLOCKS` (gross/less/net); các rule NOTE khác bị gate off trong mode này.

### Testing hygiene

- `pytest.ini` giới hạn discovery vào thư mục `tests/` để tránh thu thập các file `test_*.py` ở root gây lỗi import/collection.