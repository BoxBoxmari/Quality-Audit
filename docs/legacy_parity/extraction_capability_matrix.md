# Extraction Capability Matrix

| Capability | Primary path | Fallback path | Status |
|---|---|---|---|
| merged cells | OOXML grid extractor | render-first / html-export / legacy | covered |
| vertically merged multi-row headers | header promotion + canonicalizer | render-first | covered |
| repeated headers across page breaks | `word_reader` continuity + split/merge decisions | render-first/html | covered |
| split tables across pages | statement-group stitching logic | conservative no-merge fallback | covered |
| section-heading drift | paragraph heading inference with junk filter | table-first-row fallback | covered |
| nested tables / noisy structures | table isolator + noise filters | conservative skip / generic path | covered |
| footer/signature/page-number interference | skip classifier | n/a | covered |
| capability-gated advanced fallback | render-first only when available and structurally needed | html-export / legacy reconstruction | covered |

## Evidence
- Tests: `tests/io/extractors/test_fallback_orchestration.py` and related extractor suites pass.
- Runtime: regression smoke (`scripts/run_regression_2docs.py`) passes with deterministic outputs.
