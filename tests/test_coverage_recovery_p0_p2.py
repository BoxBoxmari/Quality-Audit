"""
Tests for P0–P2: Audit Engine Coverage & Correctness Recovery.

Covers:
- canonical_table_type mapping
- BasicNumericChecksRule (B1 vertical sum, B2 tie-out)
- Gate semantics: is_structure_undetermined → warn + continue
- Registry miss → REGISTRY_MISS evidence
- UNVERIFIED_NUMERIC_TABLE fallback
"""

import pandas as pd
import pytest

from quality_audit.config.constants import (
    SKIP_REASON_NO_RULES_FOR_TYPE,
    SKIP_REASON_REGISTRY_MISS,
    SKIP_REASON_RULES_RAN_NO_EVIDENCE,
    WARN_REASON_STRUCTURE_UNDETERMINED,
)
from quality_audit.core.evidence import ValidationEvidence
from quality_audit.core.materiality import MaterialityEngine
from quality_audit.core.rules.basic_numeric_checks import BasicNumericChecksRule
from quality_audit.core.rules.rule_registry import RuleRegistry
from quality_audit.core.validators.audit_grade_validator import AuditGradeValidator
from quality_audit.utils.canonical_table_type import canonical_table_type


# ---------------------------------------------------------------------------
# canonical_table_type tests
# ---------------------------------------------------------------------------
class TestCanonicalTableType:
    def test_snake_case_to_upper(self):
        assert canonical_table_type("fs_balance_sheet") == "FS_BALANCE_SHEET"

    def test_already_upper(self):
        assert canonical_table_type("GENERIC_NOTE") == "GENERIC_NOTE"

    def test_none_returns_unknown(self):
        assert canonical_table_type(None) == "UNKNOWN"

    def test_empty_string_returns_unknown(self):
        assert canonical_table_type("") == "UNKNOWN"

    def test_unknown_value(self):
        assert canonical_table_type("unknown") == "UNKNOWN"

    def test_tax_note(self):
        assert canonical_table_type("tax_note") == "TAX_NOTE"

    def test_generic_note(self):
        assert canonical_table_type("generic_note") == "GENERIC_NOTE"

    def test_unrecognised_fallback_upper(self):
        assert canonical_table_type("custom_type") == "CUSTOM_TYPE"


# ---------------------------------------------------------------------------
# BasicNumericChecksRule tests
# ---------------------------------------------------------------------------
class TestBasicNumericChecksRule:
    @pytest.fixture
    def materiality(self):
        return MaterialityEngine()

    @pytest.fixture
    def rule(self):
        return BasicNumericChecksRule()

    def test_b1_vertical_sum_pass(self, rule, materiality):
        """B1: Sum of detail rows matches total → PASS (non-material)."""
        df = pd.DataFrame(
            {
                "Description": ["Item A", "Item B", "Total"],
                "Amount": [100, 200, 300],
            }
        )
        evidence = rule.evaluate(
            df,
            materiality=materiality,
            table_type="GENERIC_NOTE",
            table_id="tbl_001",
            amount_cols=["Amount"],
            label_col="Description",
        )
        assert len(evidence) >= 1
        b1 = [e for e in evidence if "B1" in e.assertion_text]
        assert len(b1) >= 1
        assert b1[0].is_material is False
        assert b1[0].metadata["check_engine"] == "basic_numeric"

    def test_b1_vertical_sum_fail(self, rule, materiality):
        """B1: Sum mismatch exceeding tolerance → material evidence."""
        df = pd.DataFrame(
            {
                "Description": ["Item A", "Item B", "Total"],
                "Amount": [100, 200, 999_999],  # huge mismatch
            }
        )
        evidence = rule.evaluate(
            df,
            materiality=materiality,
            table_type="GENERIC_NOTE",
            table_id="tbl_002",
            amount_cols=["Amount"],
            label_col="Description",
        )
        b1 = [e for e in evidence if "B1" in e.assertion_text]
        assert len(b1) >= 1
        assert b1[0].is_material is True

    def test_b1_with_negatives(self, rule, materiality):
        """B1: Handles negative values correctly."""
        df = pd.DataFrame(
            {
                "Description": ["Revenue", "Expenses", "Total"],
                "Amount": [500, -200, 300],
            }
        )
        evidence = rule.evaluate(
            df,
            materiality=materiality,
            table_type="GENERIC_NOTE",
            table_id="tbl_003",
            amount_cols=["Amount"],
            label_col="Description",
        )
        b1 = [e for e in evidence if "B1" in e.assertion_text]
        assert len(b1) >= 1
        assert b1[0].is_material is False

    def test_b1_with_blanks(self, rule, materiality):
        """B1: Blank/None values treated as 0."""
        df = pd.DataFrame(
            {
                "Description": ["Item A", "Item B", "Total"],
                "Amount": [100, None, 100],
            }
        )
        evidence = rule.evaluate(
            df,
            materiality=materiality,
            table_type="GENERIC_NOTE",
            table_id="tbl_004",
            amount_cols=["Amount"],
            label_col="Description",
        )
        b1 = [e for e in evidence if "B1" in e.assertion_text]
        assert len(b1) >= 1
        assert b1[0].is_material is False

    def test_b1_vietnamese_total(self, rule, materiality):
        """B1: Detects Vietnamese 'Tổng' as total row."""
        df = pd.DataFrame(
            {
                "Mô tả": ["Khoản A", "Khoản B", "Tổng cộng"],
                "Số tiền": [1000, 2000, 3000],
            }
        )
        evidence = rule.evaluate(
            df,
            materiality=materiality,
            table_type="GENERIC_NOTE",
            table_id="tbl_005",
            amount_cols=["Số tiền"],
            label_col="Mô tả",
        )
        b1 = [e for e in evidence if "B1" in e.assertion_text]
        assert len(b1) >= 1
        assert b1[0].is_material is False

    def test_b2_tie_out_pass(self, rule, materiality):
        """B2: OB + movements = CB → PASS."""
        df = pd.DataFrame(
            {
                "Description": [
                    "Opening balance",
                    "Additions",
                    "Depreciation",
                    "Closing balance",
                ],
                "Amount": [1000, 200, -50, 1150],
            }
        )
        evidence = rule.evaluate(
            df,
            materiality=materiality,
            table_type="GENERIC_NOTE",
            table_id="tbl_006",
            amount_cols=["Amount"],
            label_col="Description",
            ob_row_idx=0,
            cb_row_idx=3,
            movement_rows=[1, 2],
        )
        b2 = [e for e in evidence if "B2" in e.assertion_text]
        assert len(b2) >= 1
        assert b2[0].is_material is False

    def test_b2_tie_out_fail(self, rule, materiality):
        """B2: OB + movements ≠ CB → material evidence."""
        df = pd.DataFrame(
            {
                "Description": ["Opening balance", "Additions", "Closing balance"],
                "Amount": [1000, 200, 5000],  # CB should be 1200
            }
        )
        evidence = rule.evaluate(
            df,
            materiality=materiality,
            table_type="GENERIC_NOTE",
            table_id="tbl_007",
            amount_cols=["Amount"],
            label_col="Description",
            ob_row_idx=0,
            cb_row_idx=2,
            movement_rows=[1],
        )
        b2 = [e for e in evidence if "B2" in e.assertion_text]
        assert len(b2) >= 1
        assert b2[0].is_material is True

    def test_empty_amount_cols_returns_empty(self, rule, materiality):
        """No amount cols → no evidence."""
        df = pd.DataFrame({"Description": ["A", "B"]})
        evidence = rule.evaluate(
            df,
            materiality=materiality,
            table_type="GENERIC_NOTE",
            table_id="tbl_008",
            amount_cols=[],
        )
        assert evidence == []

    def test_low_confidence_metadata(self, rule, materiality):
        """Low confidence flag propagates to metadata."""
        df = pd.DataFrame(
            {
                "Description": ["Item A", "Total"],
                "Amount": [100, 100],
            }
        )
        evidence = rule.evaluate(
            df,
            materiality=materiality,
            table_type="GENERIC_NOTE",
            table_id="tbl_009",
            amount_cols=["Amount"],
            label_col="Description",
            low_confidence=True,
        )
        b1 = [e for e in evidence if "B1" in e.assertion_text]
        assert len(b1) >= 1
        assert b1[0].metadata["low_confidence"] is True
        assert b1[0].confidence == 0.5


# ---------------------------------------------------------------------------
# Gate semantics tests (P1: no hard gate)
# ---------------------------------------------------------------------------
class TestGateSemantics:
    @pytest.fixture
    def materiality(self):
        return MaterialityEngine()

    def test_structure_undetermined_emits_warn_and_continues(self, materiality):
        """is_structure_undetermined → emits WARN but does NOT block rules."""
        registry = RuleRegistry()
        registry.register("GENERIC_NOTE", BasicNumericChecksRule)
        auditor = AuditGradeValidator(registry, materiality)

        df = pd.DataFrame(
            {
                "Description": ["Item A", "Item B", "Total"],
                "Amount": [100, 200, 300],
            }
        )

        table_info = {
            "table_type": "GENERIC_NOTE",
            "df": df,
            "table_id": "tbl_gate_01",
            "amount_cols": ["Amount"],
            "is_structure_undetermined": True,
        }

        evidence = auditor.validate_table(table_info)

        # Must contain the WARN
        warn_ev = [e for e in evidence if e.rule_id == "NOTE_STRUCTURE_UNDETERMINED"]
        assert len(warn_ev) == 1
        assert (
            warn_ev[0].metadata.get("reason_code") == WARN_REASON_STRUCTURE_UNDETERMINED
        )

        # Must also contain rule evidence (BasicNumericChecks ran)
        rule_ev = [e for e in evidence if e.rule_id == "BASIC_NUMERIC_CHECKS"]
        assert len(rule_ev) >= 1, "Rules must run despite is_structure_undetermined"

    def test_structure_ok_runs_rules_normally(self, materiality):
        """Normal path: structure OK but no applicable primary rules → UNVERIFIED evidence."""
        registry = RuleRegistry()
        registry.register("GENERIC_NOTE", BasicNumericChecksRule)
        auditor = AuditGradeValidator(registry, materiality)

        df = pd.DataFrame(
            {
                "Description": ["Item A", "Total"],
                "Amount": [100, 100],
            }
        )

        table_info = {
            "table_type": "GENERIC_NOTE",
            "df": df,
            "table_id": "tbl_gate_02",
            "amount_cols": ["Amount"],
        }

        evidence = auditor.validate_table(table_info)
        warn_ev = [e for e in evidence if e.rule_id == "NOTE_STRUCTURE_UNDETERMINED"]
        assert len(warn_ev) == 0, "No WARN when structure is determined"

        unverified = [e for e in evidence if e.rule_id == "UNVERIFIED_NUMERIC_TABLE"]
        assert len(unverified) == 1

    def test_invalid_table_info_numeric_emits_unverified(self, materiality):
        """Invalid table_info (no table_type) + numeric → UNVERIFIED evidence."""
        registry = RuleRegistry()
        auditor = AuditGradeValidator(registry, materiality)

        table_info = {
            "table_type": None,
            "df": None,
            "amount_cols": ["Amount"],
        }

        evidence = auditor.validate_table(table_info)
        assert len(evidence) == 1
        assert evidence[0].rule_id == "UNVERIFIED_NUMERIC_TABLE"

    def test_invalid_table_info_non_numeric_returns_empty(self, materiality):
        """Invalid table_info (no table_type) + non-numeric → empty."""
        registry = RuleRegistry()
        auditor = AuditGradeValidator(registry, materiality)

        table_info = {
            "table_type": None,
            "df": None,
            "amount_cols": [],
        }

        evidence = auditor.validate_table(table_info)
        assert evidence == []


# ---------------------------------------------------------------------------
# Registry miss tests (P2)
# ---------------------------------------------------------------------------
class TestRegistryMiss:
    @pytest.fixture
    def materiality(self):
        return MaterialityEngine()

    def test_unknown_type_numeric_emits_registry_miss(self, materiality):
        """UNKNOWN type + numeric → REGISTRY_MISS + UNVERIFIED evidence."""
        registry = RuleRegistry()
        # No rules registered for "UNKNOWN"
        auditor = AuditGradeValidator(registry, materiality)

        df = pd.DataFrame(
            {
                "Description": ["A", "B"],
                "Amount": [100, 200],
            }
        )

        table_info = {
            "table_type": "UNKNOWN",
            "df": df,
            "table_id": "tbl_miss_01",
            "amount_cols": ["Amount"],
        }

        evidence = auditor.validate_table(table_info)
        unverified = [e for e in evidence if e.rule_id == "UNVERIFIED_NUMERIC_TABLE"]
        assert len(unverified) == 1
        assert SKIP_REASON_REGISTRY_MISS in unverified[0].assertion_text

    def test_known_type_non_numeric_no_evidence_ok(self, materiality):
        """Non-numeric table with no rules → empty evidence (acceptable)."""
        registry = RuleRegistry()
        auditor = AuditGradeValidator(registry, materiality)

        df = pd.DataFrame(
            {
                "Description": ["Narrative text", "More text"],
            }
        )

        table_info = {
            "table_type": "UNKNOWN",
            "df": df,
            "table_id": "tbl_miss_02",
            "amount_cols": [],
        }

        evidence = auditor.validate_table(table_info)
        assert evidence == []

    def test_rules_ran_but_no_evidence_emits_unverified(self, materiality):
        """Rules exist and ran but produced no evidence → UNVERIFIED."""
        # Create a dummy rule that always returns empty
        from quality_audit.core.rules.base_rule import AuditRule

        class NoOpRule(AuditRule):
            rule_id = "NOOP"

            def evaluate(self, df, *, materiality, table_type, **kwargs):
                return []

        registry = RuleRegistry()
        registry.register("GENERIC_NOTE", NoOpRule)
        auditor = AuditGradeValidator(registry, materiality)

        df = pd.DataFrame(
            {
                "Description": ["A", "B"],
                "Amount": [100, 200],
            }
        )

        table_info = {
            "table_type": "GENERIC_NOTE",
            "df": df,
            "table_id": "tbl_noop_01",
            "amount_cols": ["Amount"],
        }

        evidence = auditor.validate_table(table_info)
        unverified = [e for e in evidence if e.rule_id == "UNVERIFIED_NUMERIC_TABLE"]
        assert len(unverified) == 1
        assert SKIP_REASON_RULES_RAN_NO_EVIDENCE in unverified[0].assertion_text
