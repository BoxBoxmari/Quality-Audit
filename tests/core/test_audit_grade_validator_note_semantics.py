import pandas as pd

from quality_audit.config.constants import (
    WARN_REASON_SCOPE_UNDETERMINED,
    WARN_REASON_STRUCTURE_INCOMPLETE,
)
from quality_audit.core.materiality.materiality_engine import MaterialityEngine
from quality_audit.core.rules.basic_numeric_checks import BasicNumericChecksRule
from quality_audit.core.rules.movement_by_columns import MovementByColumnsRule
from quality_audit.core.rules.movement_equation import MovementEquationRule
from quality_audit.core.rules.scoped_vertical_sum import ScopedVerticalSumRule
from quality_audit.core.validators.audit_grade_validator import AuditGradeValidator


class _DummyRegistry:
    """Minimal registry stub that always returns the provided rules list."""

    def __init__(self, rules):
        self._rules = rules

    def resolve(self, table_type: str):
        return list(self._rules)


class _SpyBasicNumericRule:
    """Spy implementation for BASIC_NUMERIC_CHECKS to assert gating behavior."""

    rule_id = "BASIC_NUMERIC_CHECKS"

    def __init__(self) -> None:
        self.called = False

    def evaluate(self, **kwargs):
        self.called = True
        return []


def _make_simple_numeric_df() -> pd.DataFrame:
    return pd.DataFrame(
        {
            "Description": ["A", "B"],
            "Amount": [1, 2],
        }
    )


def test_no_total_validation_mode_suppresses_structure_and_scope_warns():
    """
    LISTING/NO_TOTAL notes must not emit STRUCTURE_INCOMPLETE or SCOPE_UNDETERMINED
    WARNs from movement/vertical-sum rules.
    """
    df = _make_simple_numeric_df()
    registry = _DummyRegistry([MovementEquationRule(), ScopedVerticalSumRule()])
    validator = AuditGradeValidator(registry=registry, materiality=MaterialityEngine())

    table_info = {
        "df": df,
        "table_type": "GENERIC_NOTE",
        "table_id": "NO_TOTAL_WARN_GATING",
        "amount_cols": ["Amount"],
        # Explicit NO_TOTAL/listing semantics
        "is_structure_undetermined": False,
        "note_mode": "NO_TOTAL_DECLARED",
        "structure_status": "STRUCTURE_NO_TOTAL",
        "note_validation_mode": "LISTING_NO_TOTAL",
        # NOTE structure output
        "segments": [],
        "scopes": [],
        "is_movement_table": False,
    }

    evidence = validator.validate_table(table_info)
    reason_codes = {getattr(e, "reason_code", "") for e in evidence}
    assert WARN_REASON_STRUCTURE_INCOMPLETE not in reason_codes
    assert WARN_REASON_SCOPE_UNDETERMINED not in reason_codes


def test_movement_equation_emits_structure_incomplete_when_anchors_missing():
    """
    MovementEquationRule must still emit STRUCTURE_INCOMPLETE when the planner
    classifies the table as movement-by-rows and anchors are missing.
    """
    df = _make_simple_numeric_df()
    rule = MovementEquationRule()
    materiality = MaterialityEngine()

    # Simulate one segment discovered by the movement scanner but with all
    # anchors missing (ob/cb/movement_rows). In movement-by-rows mode this
    # must still yield STRUCTURE_INCOMPLETE.
    from types import SimpleNamespace

    seg = SimpleNamespace(
        ob_row_idx=None,
        cb_row_idx=None,
        movement_rows=None,
        segment_name="broken",
        start_row=0,
        end_row=2,
        confidence=1.0,
    )
    # When the planner explicitly classifies the table as non‑movement,
    # the rule must be gated off and emit no STRUCTURE_INCOMPLETE WARNs.
    evidence_gated = rule.evaluate(
        df,
        materiality=materiality,
        table_type="GENERIC_NOTE",
        table_id="MOVEMENT_GATED",
        amount_cols=["Amount"],
        ob_row_idx=None,
        cb_row_idx=None,
        movement_rows=None,
        is_movement_table=True,
        note_validation_mode="LISTING_NO_TOTAL",
    )
    assert all(
        getattr(e, "reason_code", None) != WARN_REASON_STRUCTURE_INCOMPLETE
        for e in evidence_gated
    ), "Expected no STRUCTURE_INCOMPLETE when validation_mode=LISTING_NO_TOTAL"


def test_movement_by_columns_routed_and_movement_by_rows_skipped():
    """
    When validation_mode=MOVEMENT_BY_COLUMNS, only MovementByColumnsRule should
    execute; MovementEquationRule (by-rows) must be skipped.
    """
    df = pd.DataFrame(
        {
            "Opening balance": [100],
            "Increase": [10],
            "Closing balance": [120],  # Deliberate mismatch (should be 110)
        }
    )

    registry = _DummyRegistry([MovementEquationRule(), MovementByColumnsRule()])
    validator = AuditGradeValidator(registry=registry, materiality=MaterialityEngine())

    table_info = {
        "df": df,
        "table_type": "GENERIC_NOTE",
        "table_id": "MBC_ROUTING",
        "amount_cols": ["Opening balance", "Increase", "Closing balance"],
        "note_validation_mode": "MOVEMENT_BY_COLUMNS",
        "note_validation_plan": {
            "ob_col": "Opening balance",
            "cb_col": "Closing balance",
            "movement_cols": ["Increase"],
        },
    }

    evidence = validator.validate_table(table_info)
    rule_ids = {e.rule_id for e in evidence}
    # Expect MovementByColumnsRule to run and MovementEquationRule to be skipped.
    assert "MOVEMENT_BY_COLUMNS" in rule_ids
    assert "MOVEMENT_EQUATION" not in rule_ids


def test_scoped_totals_with_scopes_runs_vertical_sum_without_warn():
    """
    Scoped-total mode with explicit planner scopes should run
    ScopedVerticalSumRule and not emit SCOPE_UNDETERMINED WARNs.
    """
    df = pd.DataFrame(
        {
            "Description": ["A", "B", "Total"],
            "Amount": [10, 20, 30],
        }
    )
    registry = _DummyRegistry([ScopedVerticalSumRule()])
    validator = AuditGradeValidator(registry=registry, materiality=MaterialityEngine())

    table_info = {
        "df": df,
        "table_type": "GENERIC_NOTE",
        "table_id": "SCOPED_OK",
        "amount_cols": ["Amount"],
        "note_validation_mode": "LISTING_TOTALS",
        # Planner-provided scope: rows 0–1 sum to row 2.
        "scopes": [{"detail_rows": [0, 1], "total_row_idx": 2}],
    }

    evidence = validator.validate_table(table_info)
    reason_codes = {getattr(e, "reason_code", None) for e in evidence}
    assert WARN_REASON_SCOPE_UNDETERMINED not in reason_codes


def test_scoped_totals_without_scopes_produces_skip_info_not_warn():
    """
    When note_validation_mode is a scoped-total variant but no scopes are
    available, ScopedVerticalSumRule must emit only an INFO skip evidence
    with skip_reason=SCOPES_NOT_PLANNED and must not produce WARNs.
    """
    df = _make_simple_numeric_df()
    registry = _DummyRegistry([ScopedVerticalSumRule()])
    validator = AuditGradeValidator(registry=registry, materiality=MaterialityEngine())

    table_info = {
        "df": df,
        "table_type": "GENERIC_NOTE",
        "table_id": "SCOPED_SKIP",
        "amount_cols": ["Amount"],
        # Scoped-total mode but no scopes in table_info: this should be
        # treated as an informational skip, not a structural WARN.
        "note_validation_mode": "SCOPED_TOTAL",
    }

    evidence = validator.validate_table(table_info)
    # Expect at least one INFO evidence tagged with SCOPES_NOT_PLANNED.
    skip_evidence = [
        e
        for e in evidence
        if isinstance(getattr(e, "metadata", {}), dict)
        and e.metadata.get("skip_reason") == "SCOPES_NOT_PLANNED"
    ]
    assert skip_evidence, "Expected SCOPES_NOT_PLANNED skip evidence in scoped-total mode"

    reason_codes = {getattr(e, "reason_code", None) for e in evidence}
    assert WARN_REASON_SCOPE_UNDETERMINED not in reason_codes

def test_fallback_numeric_blocked_for_no_total_note_mode():
    """
    Phase 2: tables explicitly marked as NO_TOTAL / LISTING / SINGLE_ROW
    must not execute BASIC_NUMERIC_CHECKS even when numeric.
    """
    df = _make_simple_numeric_df()
    spy_rule = _SpyBasicNumericRule()
    registry = _DummyRegistry([spy_rule])
    validator = AuditGradeValidator(registry=registry, materiality=MaterialityEngine())

    table_info = {
        "df": df,
        "table_type": "GENERIC_NOTE",
        "table_id": "NO_TOTAL_1",
        "amount_cols": ["Amount"],
        # Semantics: explicit NO_TOTAL declaration
        "is_structure_undetermined": False,
        "note_mode": "NO_TOTAL_DECLARED",
        "structure_status": "STRUCTURE_NO_TOTAL",
    }

    evidence = validator.validate_table(table_info)

    # BASIC_NUMERIC_CHECKS must not be called at all.
    assert spy_rule.called is False
    # Numeric tables without real evidence still get a single UNVERIFIED marker.
    rule_ids = {e.rule_id for e in evidence}
    assert "UNVERIFIED_NUMERIC_TABLE" in rule_ids


def test_fallback_numeric_runs_when_structure_really_undetermined():
    """
    When structure is genuinely undetermined, low_confidence must be set and
    BASIC_NUMERIC_CHECKS is allowed to run as a diagnostics pass.
    """
    df = _make_simple_numeric_df()
    spy_rule = _SpyBasicNumericRule()
    registry = _DummyRegistry([spy_rule])
    validator = AuditGradeValidator(registry=registry, materiality=MaterialityEngine())

    table_info = {
        "df": df,
        "table_type": "GENERIC_NOTE",
        "table_id": "UNDETERMINED_1",
        "amount_cols": ["Amount"],
        # Semantics: analyzer could not determine structure
        "is_structure_undetermined": True,
        "note_mode": "",
        "structure_status": "",
    }

    evidence = validator.validate_table(table_info)

    # Fallback rule must be executed in this case.
    assert spy_rule.called is True
    rule_ids = {e.rule_id for e in evidence}
    # We expect a NOTE_STRUCTURE_UNDETERMINED WARN plus an UNVERIFIED marker.
    assert "NOTE_STRUCTURE_UNDETERMINED" in rule_ids
    assert "UNVERIFIED_NUMERIC_TABLE" in rule_ids

