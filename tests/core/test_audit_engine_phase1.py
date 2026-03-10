"""
Tests for Phase 1 foundation modules:
  - MaterialityEngine
  - ValidationEvidence + Severity
  - AuditRule base class
  - RuleRegistry
"""

import pytest

from quality_audit.core.evidence import Severity, ValidationEvidence
from quality_audit.core.materiality import MaterialityEngine
from quality_audit.core.rules.base_rule import AuditRule
from quality_audit.core.rules.rule_registry import RuleRegistry

# ---------------------------------------------------------------------------
# Severity
# ---------------------------------------------------------------------------


class TestSeverity:
    def test_ordering(self):
        assert Severity.INFO < Severity.MINOR < Severity.MAJOR < Severity.CRITICAL

    def test_deductions(self):
        assert Severity.CRITICAL.deduction == 25
        assert Severity.MAJOR.deduction == 10
        assert Severity.MINOR.deduction == 3
        assert Severity.INFO.deduction == 0

    def test_value_strings(self):
        assert Severity.CRITICAL.value == "CRITICAL"
        assert Severity.INFO.value == "INFO"


# ---------------------------------------------------------------------------
# ValidationEvidence
# ---------------------------------------------------------------------------


class TestValidationEvidence:
    def test_pass_factory(self):
        ev = ValidationEvidence.pass_evidence(
            rule_id="TEST_RULE",
            assertion_text="A = B",
            expected=100.0,
            actual=100.5,
            tolerance=1.0,
        )
        assert ev.is_material is False
        assert ev.severity == Severity.INFO
        assert ev.diff == pytest.approx(0.5)

    def test_fail_factory(self):
        ev = ValidationEvidence.fail_evidence(
            rule_id="TEST_RULE",
            assertion_text="A = B",
            expected=100.0,
            actual=110.0,
            tolerance=1.0,
            severity=Severity.MAJOR,
        )
        assert ev.is_material is True
        assert ev.severity == Severity.MAJOR
        assert ev.diff == pytest.approx(10.0)

    def test_to_dict(self):
        ev = ValidationEvidence.pass_evidence(
            rule_id="R1",
            assertion_text="X",
            expected=0,
            actual=0,
            tolerance=1.0,
        )
        d = ev.to_dict()
        assert d["rule_id"] == "R1"
        assert d["severity"] == "INFO"
        assert "expected" in d
        assert "actual" in d


# ---------------------------------------------------------------------------
# MaterialityEngine
# ---------------------------------------------------------------------------


class TestMaterialityEngine:
    def test_compute_scales_with_value(self):
        engine = MaterialityEngine()
        # IS at 1M → tolerance = 0.005 * 1M = 5000
        tol = engine.compute(1_000_000, "INCOME_STATEMENT")
        assert tol == pytest.approx(5_000.0)

    def test_compute_floor(self):
        engine = MaterialityEngine()
        # Very small value → should hit floor (1.0)
        tol = engine.compute(10.0, "BALANCE_SHEET")
        # 0.001 * 10 = 0.01, floor = 1.0
        assert tol == pytest.approx(1.0)

    def test_compute_ceiling(self):
        engine = MaterialityEngine(ceiling_abs=100.0)
        tol = engine.compute(1_000_000, "NOTE_BREAKDOWN")
        # 0.008 * 1M = 8000, but ceiling = 100
        assert tol == pytest.approx(100.0)

    def test_is_material_true(self):
        engine = MaterialityEngine()
        assert (
            engine.is_material(
                diff=10_000, value=1_000_000, table_type="INCOME_STATEMENT"
            )
            is True
        )

    def test_is_material_false(self):
        engine = MaterialityEngine()
        assert (
            engine.is_material(diff=100, value=1_000_000, table_type="INCOME_STATEMENT")
            is False
        )

    def test_unknown_table_type_uses_fallback(self):
        engine = MaterialityEngine()
        tol = engine.compute(100_000, "UNKNOWN_TYPE")
        # fallback = 0.008 * 100K = 800
        assert tol == pytest.approx(800.0)

    def test_classify_severity(self):
        engine = MaterialityEngine()
        assert (
            engine.classify_severity(diff=0.5, value=1000, table_type="BALANCE_SHEET")
            == "INFO"
        )
        # BS tol = 0.001 * 1000 = 1.0; diff=2 → ratio=2 → MINOR
        assert (
            engine.classify_severity(diff=2, value=1000, table_type="BALANCE_SHEET")
            == "MINOR"
        )
        # diff=5 → ratio=5 → MAJOR (ratio > 3)
        assert (
            engine.classify_severity(diff=5, value=1000, table_type="BALANCE_SHEET")
            == "MAJOR"
        )
        # CRITICAL: ratio > 10 → diff > 10 * tol(1.0) = 10, so diff=20 at value=5 → tol=1.0, ratio=20
        assert (
            engine.classify_severity(diff=20, value=5, table_type="BALANCE_SHEET")
            == "CRITICAL"
        )

    def test_custom_profile(self):
        engine = MaterialityEngine(profile={"CUSTOM": 0.01})
        tol = engine.compute(100_000, "CUSTOM")
        assert tol == pytest.approx(1_000.0)


# ---------------------------------------------------------------------------
# RuleRegistry
# ---------------------------------------------------------------------------


class _DummyRule(AuditRule):
    rule_id = "DUMMY"
    description = "Test rule"

    def evaluate(self, df, *, materiality, table_type, **kwargs):
        return []


class TestRuleRegistry:
    def test_register_and_resolve(self):
        reg = RuleRegistry()
        reg.register("TEST_TYPE", _DummyRule)
        rules = reg.resolve("TEST_TYPE")
        assert len(rules) == 1
        assert isinstance(rules[0], _DummyRule)

    def test_resolve_unknown_returns_empty(self):
        reg = RuleRegistry()
        assert reg.resolve("NONEXISTENT") == []

    def test_no_duplicate_registration(self):
        reg = RuleRegistry()
        reg.register("T", _DummyRule)
        reg.register("T", _DummyRule)
        assert len(reg.resolve("T")) == 1

    def test_registered_types(self):
        reg = RuleRegistry()
        reg.register("A", _DummyRule)
        reg.register("B", _DummyRule)
        assert set(reg.registered_types) == {"A", "B"}
