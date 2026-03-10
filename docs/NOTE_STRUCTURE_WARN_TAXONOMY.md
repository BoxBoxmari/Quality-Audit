# NOTE Structure — WARN Reason Code Taxonomy and Manual Review

This document describes the WARN status and `reason_code` taxonomy used when NOTE tables have ambiguous or incomplete structure, and how to handle WARN results in manual review.

## WARN reason_code taxonomy

When a NOTE table is validated but structure or scope is ambiguous, the pipeline sets status to **WARN** and attaches a `reason_code` in evidence metadata and in table context. All codes are defined in `quality_audit/config/constants.py` as `WARN_REASON_*` and collected in `WARN_REASON_CODES`.

| reason_code | Meaning |
|-------------|--------|
| `UNKNOWN_TABLE_TYPE` | Table type could not be determined (e.g. heading missing or not matched). |
| `SCOPE_UNDETERMINED` | Total/subtotal scope or detail bounds could not be determined; multiple candidate scopes. |
| `MULTIPLE_TOTAL_CANDIDATES` | More than one row matched as total/subtotal; single total row could not be chosen. |
| `STRUCTURE_INCOMPLETE` | Movement or roll-forward structure was detected but OB/CB/movement row indices are missing or inconsistent. |
| `NUMERIC_COLUMNS_AMBIGUOUS` | Which columns are amount columns could not be determined with sufficient confidence. |
| `HEADER_CONFUSION` | Header or period detection is ambiguous (e.g. merged cells, multiple header rows). |

Rules (e.g. `MovementEquationRule`, `ScopedVerticalSumRule`) set `evidence.metadata["reason_code"]` when they emit a WARN; the validator maps any evidence with `reason_code in WARN_REASON_CODES` (or `review_required`) to status WARN and passes `reason_code` through to table context and output (e.g. Excel column, telemetry).

## Manual review workflow for WARN

1. **Identify WARN tables**  
   In the audit output (e.g. Excel or report), filter for tables with status **WARN**.

2. **Read reason_code**  
   Use the table’s `reason_code` (or `failure_reason_code` / evidence metadata) to see why the run was ambiguous. The taxonomy above explains each code.

3. **Triage by code**  
   - **STRUCTURE_INCOMPLETE**: Check if OB/CB/movement rows are clearly labeled in the source; consider template or heading fixes so the NOTE structure engine can detect them.  
   - **SCOPE_UNDETERMINED**: Identify which total row is the intended one and whether segment boundaries (e.g. section headers) need to be clearer.  
   - **MULTIPLE_TOTAL_CANDIDATES**: Resolve which row is the single total for the scope (e.g. by naming or layout).  
   - **NUMERIC_COLUMNS_AMBIGUOUS**: Confirm which columns are numeric amounts; improve header/layout so amount columns are detectable.  
   - **HEADER_CONFUSION**: Simplify headers or period layout so the detector can infer a single header and period set.  
   - **UNKNOWN_TABLE_TYPE**: Improve heading or table type hints so the table is classified (e.g. GENERIC_NOTE or movement).

4. **No automatic FAIL**  
   WARN is used so that ambiguity does not become a hard FAIL. Fix source data or templates where possible; re-run the audit to see if the same table moves to PASS or remains WARN with the same or different reason_code.

5. **Evidence and logs**  
   For debugging, use the per-table observability payload (table_id, heading, table_type, label_col, amount_cols, segments, confidence) and any evidence entries that carry `reason_code` in metadata.

## Feature flag

The NOTE structure engine is controlled by the **note_structure_engine** feature flag (`quality_audit/config/feature_flags.py`). When `True` (default), NOTE tables use `analyze_note_table()` and segment/scoped logic; when `False`, the legacy “last row as total” path is used. Rollback: set the flag to `False` and re-run without changing FS or other validators.
