# Implementation Plan: WARN Inflation Elimination & Traceability

**Version:** 1.0  
**Scope:** Quality Audit – financial-statement extraction + validation  
**Deliverable:** Plan only (no code edits). All outputs auditable via `run_id` and per-table telemetry.

---

## 1. Overview

### 1.1 Objectives

- **Eliminate systemic WARN inflation** so WARN ratio is &lt; 3% on FS2018 corpus; majority of prior WARN reclassified into PASS, FAIL_DATA, or FAIL_TOOL_*.
- **Separate tool fault from audit finding**: FAIL_TOOL_* (extraction/normalization/logic fault) vs FAIL_DATA (reliable extraction, true audit mismatch).
- **Robust extraction** for Word tables with horizontal/vertical merges and header corruption; **resilient totals detection** including blank-label totals.
- **Full traceability**: every output line tied to a `run_id` and per-table telemetry (extractor, quality score, totals candidates, failure reason).

### 1.2 Root Causes Addressed

- Single “no totals” rule emits WARN for many tables that actually have totals (e.g. blank-label totals).
- Some FAIL outcomes are tool faults (mis-parse, mis-align) but currently classified as data failures.
- Per-table telemetry is insufficient to explain status decisions.
- Extraction from merged cells and malformed headers introduces structural noise that propagates to validators.

### 1.3 Out of Scope (this iteration)

- No ML/LLM-based extraction.
- No change to business logic of validators beyond status taxonomy and totals-detection robustness.
- No removal of existing output columns; only extension with new fields and deterministic mapping.

---

## 2. Requirements

### 2.1 Status Taxonomy

| Status | Meaning |
|--------|--------|
| PASS | Extraction reliable; all checks passed. |
| FAIL_DATA | Extraction reliable; one or more checks failed (true audit finding). |
| FAIL_TOOL_EXTRACT | Table structurally unreliable (grid corruption, header collapse, duplicate-period artifacts). |
| FAIL_TOOL_LOGIC | Extraction reliable but validator crashed or internal bug. |
| INFO_SKIPPED | Not applicable (non-financial, footer, signature, narrative, no numeric columns). |

**Mapping rules:**

- Table structurally unreliable (grid corruption, header collapse, duplicate-period artifacts) → **FAIL_TOOL_EXTRACT**.
- Extraction reliable but validator crashes/bugs → **FAIL_TOOL_LOGIC**.
- Extraction reliable and check fails → **FAIL_DATA**.
- Rule not applicable (no numeric columns / purely narrative) → **INFO_SKIPPED**.

**Governance:** WARN reserved for rare (&lt; 1–3%) minor issues where audit still proceeds; primary statements that lack totals due to structural issues → **FAIL_TOOL_EXTRACT**, not WARN.

### 2.2 Extractor Upgrade

- **Primary engine:** OOXML grid reconstructor (`quality_audit/io/extractors/ooxml_table_grid_extractor.py`) — already implements `tblGrid`/`gridCol`, `gridSpan`, `vMerge`, `ExtractionResult` with `quality_score`, `quality_flags`, `invariant_violations`, `failure_reason_code`, `is_usable`.
- **Canonical contract:** `matrix[row][col]` with empties as `None`; provenance (source XML path) optional but recommended for audit.
- **Fallbacks:** Existing python-docx extractor; optional tertiary docx→html/xlsx pipeline. Selection by quality scoring (see Multi-Engine Fallback).

### 2.3 Normalization & Totals Inference

- **Column typing:** TEXT, CODE/NOTE, NUMERIC_CY, NUMERIC_PY, OTHER; drop CODE/NOTE from arithmetic checks.
- **Header consolidation:** Multi-row headers; consolidated header per column; duplicate period detection → structural warning flag.
- **Numeric parsing:** Thousand separators, parentheses negatives, dash placeholders, mixed whitespace, stray currency; output NaN for non-numeric.
- **Totals detection:** At least one of:
  - **Rule A:** Keyword in label (total, subtotal, net, gross) — already in `row_classifier.TOTAL_KEYWORDS` and base_validator.
  - **Rule B:** Last numeric-dense row in block where left label is blank or punctuation-only.
  - **Rule C:** Row satisfying sum-of-previous within tolerance across ≥ X% numeric columns.
- **Decision policy:** Totals solvable and consistent → PASS; solvable but inconsistent → FAIL_DATA; totals not found due to structural unreliability → FAIL_TOOL_EXTRACT; no meaningful numeric structure → INFO_SKIPPED.
- **Tolerance:** Configurable absolute and relative (e.g. abs ≤ 1, rel ≤ 0.5%); record in telemetry.

### 2.4 Multi-Engine Fallback

- **Engines:** A = OOXML grid, B = python-docx, C = docx→html/xlsx (optional).
- **Quality scoring (per table, per engine):** row_shape_stability, duplicate_header_penalty, numeric_column_coherence, totals_solvability_score, suspicious_column_artifacts (e.g. Code.1/Column_7 duplicates). Choose engine with highest score above threshold; else FAIL_TOOL_EXTRACT.
- **Telemetry:** Always log engine chosen, quality_score, and reasons.

### 2.5 Telemetry & Traceability

- **run_id:** Generated once per run; stamped in logs, output workbook metadata, and per-table results. Already present in `telemetry_collector.run_telemetry.run_id` and `excel_writer` (summary + FS sheet).
- **Per-table telemetry fields:** table_id, table_name, validator, extractor_engine, header_rows_detected, consolidated_headers, numeric_cols_count, code_cols_count, totals_candidates_found, totals_equations_solved, quality_score, quality_flags, final_status (taxonomy), failure_reason_code, human_readable_reason.
- **Output contract:** Extend output workbook with StatusCategory (PASS/FAIL_DATA/FAIL_TOOL_EXTRACT/FAIL_TOOL_LOGIC/INFO_SKIPPED), FailureReasonCode, ExtractorEngine, QualityScore, RunId. Keep backward compatibility: existing Status/WARN columns remain with deterministic mapping from new taxonomy.

### 2.6 Acceptance Criteria

- WARN ratio &lt; 3% on FS2018 corpus; majority of prior WARN reclassified to PASS/FAIL_DATA/FAIL_TOOL_EXTRACT.
- Any primary-statement table lacking totals due to structural issues → FAIL_TOOL_EXTRACT, not WARN.
- Totals detection recall improves for blank-label totals → PASS or FAIL_DATA (not WARN).
- Every output line traceable: run_id + per-table telemetry present.

---

## 3. Implementation Steps

### Phase 1: Taxonomy & Status Mapping

**Goal:** Introduce StatusCategory and FailureReasonCode; map existing Status/WARN into new taxonomy without changing validator logic yet.

| Step | Action | Touch-points |
|------|--------|--------------|
| 1.1 | Define enum/constants for StatusCategory (PASS, FAIL_DATA, FAIL_TOOL_EXTRACT, FAIL_TOOL_LOGIC, INFO_SKIPPED) and FailureReasonCode (extend existing RULE_TAXONOMY / root cause in `config/constants.py`). | `quality_audit/config/constants.py` |
| 1.2 | Add mapping: existing Status (PASS/WARN/FAIL) + context (extractor_engine, quality_score, failure_reason_code) → StatusCategory and FailureReasonCode. Rule: if failure_reason_code indicates TOOL (e.g. EXTRACTION_FAILED, EMPTY_GRID, grid_corruption) → FAIL_TOOL_EXTRACT; if validator exception → FAIL_TOOL_LOGIC; else preserve FAIL→FAIL_DATA, WARN→WARN only when explicitly allowed (&lt; 3% target). | `quality_audit/core/validators/base_validator.py`, result-to-dict path |
| 1.3 | Ensure audit_service and excel_writer receive and persist StatusCategory, FailureReasonCode in results and sheets. | `quality_audit/services/audit_service.py`, `quality_audit/io/excel_writer.py` |

**Phase 1 status:** Done (constants, base_validator mapping + to_dict, excel_writer summary sheet columns; audit_service uses result.to_dict() unchanged). Verified: tests/test_base_validator, test_generic_validator, test_audit_service_integration pass.

### Phase 2: Extractor Robustness & Fallback

**Goal:** Use OOXML extractor as primary; fallback to python-docx when quality below threshold; optional tertiary engine; stamp extractor_engine and quality_score on table_context.

| Step | Action | Touch-points |
|------|--------|--------------|
| 2.1 | In `word_reader._extract_table_with_fallback`: call OOXML extractor first; if `ExtractionResult.is_usable` is True, use its grid and set table_context (extractor_engine, quality_score, quality_flags, failure_reason_code). | `quality_audit/io/word_reader.py` |
| 2.2 | If not usable, try python-docx extractor; compute or reuse a simple quality_score (e.g. row shape stability, no duplicate headers). Set table_context with chosen engine. | `quality_audit/io/word_reader.py`, `quality_audit/io/extractors/python_docx_extractor.py` (or current docx path) |
| 2.3 | Optional: add tertiary path (docx→html/xlsx) and quality comparison; choose best engine above threshold. | `quality_audit/io/extractors/docx_to_html_extractor.py`, `word_reader` |
| 2.4 | Ensure grid reconstruction keeps empties as None (no left-shift). OOXML extractor already returns grid; verify word_reader builds DataFrame without collapsing empty cells. | `quality_audit/io/extractors/ooxml_table_grid_extractor.py`, `quality_audit/io/word_reader.py` |

**Phase 2 status:** Done. `word_reader._extract_table_with_fallback` already calls OOXML first, then python-docx, then LibreOffice (table_index==0), then legacy; returns (grid, meta) with extractor_engine, quality_score, quality_flags, failure_reason_code; caller does `table_context.update(extract_meta)`. OOXML/python_docx extractors return ExtractionResult with is_usable, quality_score, failure_reason_code. Grid is fixed-column (empty cells as ""), no left-shift; word_reader only pads when row lengths differ.

### Phase 3: Normalization & Header Consolidation

**Goal:** Multi-row header detection; consolidated header per column; duplicate period detection; column typing (CODE/NOTE vs NUMERIC_*) for exclusion from arithmetic.

| Step | Action | Touch-points |
|------|--------|--------------|
| 3.1 | Detect header rows by low numeric density + repetition patterns (e.g. “Code”, “Note”, year). Compose consolidated header per column (stack header rows top-down). | `quality_audit/io/word_reader.py` (`_promote_header_row` / new helper), or `quality_audit/utils/column_detector.py` |
| 3.2 | Detect duplicate period headers; set structural warning flag (e.g. duplicate_period_artifacts) used for FAIL_TOOL_EXTRACT. | `quality_audit/utils/table_normalizer.py` or word_reader |
| 3.3 | Column typing: CODE/NOTE (regex “Note”, “Code”, “.”, “Ref”); NUMERIC_CY/PY; drop CODE/NOTE from totals/arithmetic; keep for display/provenance. | `quality_audit/core/validators/base_validator.py`, `quality_audit/utils/column_detector.py` |

**Phase 3 status:** 3.2 Done (duplicate_period_artifacts in table_context). 3.3 Done (note_column in metadata; NOTE+code excluded from totals). 3.1 pending.

### Phase 4: Totals Detection Hardening

**Goal:** Reduce “no totals” WARN by detecting totals with blank labels (Rule B) and sum-of-previous (Rule C); explicit decision policy and tolerance.

| Step | Action | Touch-points |
|------|--------|--------------|
| 4.1 | Rule B: In `_detect_total_rows` / `_select_total_row`, treat “last numeric-dense row in block where left label is blank or punctuation-only” as totals candidate. | `quality_audit/core/validators/base_validator.py`, `quality_audit/utils/row_classifier.py` |
| 4.2 | Rule C: Implement sum-of-previous within tolerance (configurable abs/rel); require ≥ X% numeric columns to satisfy; record totals_equations_solved in context. | `quality_audit/core/validators/base_validator.py` |
| 4.3 | Policy: If at least one totals candidate is solvable and consistent → PASS; if solvable but inconsistent → FAIL_DATA; if totals not found and table is primary statement and structural unreliability → FAIL_TOOL_EXTRACT; if no meaningful numeric structure → INFO_SKIPPED. | `quality_audit/core/validators/base_validator.py`, COLUMN_TOTAL_VALIDATION handling |
| 4.4 | Add tolerance config (absolute, relative) and log tolerance used in telemetry. | `quality_audit/config/constants.py` or validation_rules, `telemetry_collector` |

**Phase 4 status:** Done. Rule B (blank/punctuation label last numeric-dense row) and Rule C (sum-within-tolerance, min columns %) in `base_validator._find_total_row`; tolerance `TOTALS_TOLERANCE_ABS`/`TOTALS_TOLERANCE_REL`/`TOTALS_RULE_C_MIN_COLUMNS_PCT` in constants; `tolerance_used` in context; generic_validator: no totals + low quality/structural flags → FAIL_TOOL_EXTRACT (FAIL_TOOL_EXTRACT_NO_TOTALS), else WARN (TABLE_NO_TOTAL_ROW); `FAIL_TOOL_EXTRACT_NO_TOTALS` exported in constants. Tests: test_total_row_selection, test_generic_validator pass.

### Phase 5: Telemetry & Run ID

**Goal:** run_id and per-table telemetry on every output row; excel writer and logs carry full set.

| Step | Action | Touch-points |
|------|--------|--------------|
| 5.1 | Ensure run_id is set once per audit run and stored in `telemetry.run_telemetry.run_id`; already generated in `telemetry_collector`. | `quality_audit/utils/telemetry_collector.py`, `quality_audit/services/audit_service.py` |
| 5.2 | Per-table: ensure table_context and result.context contain extractor_engine, quality_score, quality_flags, failure_reason_code, totals_candidates_found, totals_equations_solved, header_rows_detected (or consolidated_headers), numeric_cols_count, code_cols_count. | `quality_audit/services/audit_service.py` (enriched_ctx), `quality_audit/core/validators/base_validator.py` |
| 5.3 | Excel: add columns StatusCategory, FailureReasonCode, ExtractorEngine, QualityScore, RunId to summary and FS sheets where applicable; keep Status/WARN for backward compatibility with deterministic mapping. | `quality_audit/io/excel_writer.py` |
| 5.4 | Logging: include run_id and key per-table fields in structured log for each table. | `quality_audit/services/audit_service.py`, existing observability_payload |

**Phase 5 status:** Done. 5.1: run_id set once per run in `TelemetryCollector.start_run()` (uuid.uuid4().hex). 5.2: table_context from word_reader has extractor_engine, quality_score, quality_flags, failure_reason_code; audit_service enriches result.context with table_context and total_row_metadata; telemetry.end_table reads result.context for per-table fields. 5.3: Summary sheet has Status Category (D), Extractor Engine (G), Quality Score (H), Failure Reason Code (I), run_id (J); FS sheet has run_id (O). 5.4: observability_payload now includes run_id, extractor_engine, quality_score, failure_reason_code.

### Phase 6: WARN Gating & Reclassification

**Goal:** Enforce WARN &lt; 3%; reclassify “no totals” WARN to PASS/FAIL_DATA/FAIL_TOOL_EXTRACT based on totals detection and structure.

| Step | Action | Touch-points |
|------|--------|--------------|
| 6.1 | Where COLUMN_TOTAL_VALIDATION currently emits WARN for “no totals”: first apply Rules A/B/C; if a totals row is found and equation holds → PASS; if found but equation fails → FAIL_DATA; if not found and table is primary statement and quality_score &lt; threshold or structural flags → FAIL_TOOL_EXTRACT; else only then allow WARN (and track to keep &lt; 3%). | `quality_audit/core/validators/base_validator.py` |
| 6.2 | Add post-run check (or test): WARN ratio on FS2018 corpus &lt; 3%. | Regression test / golden run |

**Phase 6 status:** Done. 6.1: generic_validator and base_validator already apply Rules A/B/C and map no-totals to FAIL_TOOL_EXTRACT when quality/structural flags, else WARN. 6.2: Golden regression test added in `tests/integration/test_audit_workflow.py` — `TestGoldenRegression.test_warn_ratio_below_golden_threshold` loads `acceptance.warn_ratio_max` from golden JSON (e.g. 0.03), runs `audit_service.audit_document(sample_word_file, excel_path)`, and asserts `warn_count / total <= warn_ratio_max`. Fixture `audit_service` moved to module scope so both workflow and golden tests use it.

---

## 4. Testing

### 4.1 Unit Tests

- **Taxonomy mapping:** Given mock result (Status, context with failure_reason_code, quality_score), assert StatusCategory and FailureReasonCode.
- **OOXML extractor:** Merged cells (horizontal/vertical), malformed tblGrid; assert grid shape, no left-shift of empties, quality_score and is_usable.
- **Totals Rule B:** Table with last row blank label and numeric row; assert detected as totals candidate.
- **Totals Rule C:** Table with sum-equality row; assert detected and equation solved within tolerance.
- **Header consolidation:** Multi-row header input; assert consolidated headers and column typing (CODE/NOTE excluded from arithmetic).

### 4.2 Integration Tests

- **word_reader:** Docx with merged cells → OOXML primary, fallback when OOXML returns not usable; table_context has extractor_engine and quality_score.
- **audit_service:** Full run with sample docx; results include StatusCategory, FailureReasonCode, RunId, ExtractorEngine, QualityScore; run_id consistent across results and workbook.

### 4.3 Regression & Golden Artifacts

- **FS2018 corpus:** Run full audit; measure WARN ratio (target &lt; 3%); majority of previous WARN reclassified to PASS/FAIL_DATA/FAIL_TOOL_EXTRACT.
- **Golden outputs:** Store expected StatusCategory (and optionally FailureReasonCode) for a fixed set of tables; regression test compares after changes.
- **Traceability:** For a sample run, verify every result row has run_id and per-table telemetry fields; spot-check audit trail from output back to run_id and table_id.

### 4.4 Performance

- Ensure OOXML + fallback path does not cause pathological slowdown (e.g. limit retries, cap fallback attempts); add simple timing assertion in integration test if needed.

---

## 5. File & Module Summary

| Area | Primary files |
|------|----------------|
| Taxonomy & constants | `quality_audit/config/constants.py` |
| Status mapping | `quality_audit/core/validators/base_validator.py`, result serialization |
| Extraction & fallback | `quality_audit/io/word_reader.py`, `quality_audit/io/extractors/ooxml_table_grid_extractor.py`, `python_docx_extractor`, `docx_to_html_extractor` |
| Normalization / header | `quality_audit/io/word_reader.py` (`_promote_header_row`, `_deduplicate_headers`), `quality_audit/utils/table_normalizer.py`, `quality_audit/utils/column_detector.py` |
| Totals detection | `quality_audit/core/validators/base_validator.py` (`_detect_total_rows`, `_select_total_row`), `quality_audit/utils/row_classifier.py` |
| Telemetry & run_id | `quality_audit/utils/telemetry_collector.py`, `quality_audit/services/audit_service.py` |
| Output | `quality_audit/io/excel_writer.py` |
| Table typing (primary vs notes) | `quality_audit/core/routing/table_type_classifier.py` |

---

*End of implementation plan. No code edits in this deliverable; implement in phases and verify with tests and FS2018 regression.*
