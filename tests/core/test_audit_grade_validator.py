import pandas as pd
import pytest

from quality_audit.core.evidence import Severity, ValidationEvidence
from quality_audit.core.materiality import MaterialityEngine
from quality_audit.core.model.financial_model import FinancialModel
from quality_audit.core.rules.base_rule import AuditRule
from quality_audit.core.rules.rule_registry import RuleRegistry
from quality_audit.core.validators.audit_grade_validator import AuditGradeValidator


class DummyPassRule(AuditRule):
    rule_id = "DUMMY_PASS"
    description = "Dummy pass rule"
    severity_default = Severity.INFO

    def evaluate(self, df, **kwargs):
        return [ValidationEvidence.pass_evidence("DUMMY_PASS", "Passed", 100, 100, 1.0)]


class DummyFailRule(AuditRule):
    rule_id = "DUMMY_FAIL"
    description = "Dummy fail rule"
    severity_default = Severity.MAJOR

    def evaluate(self, df, **kwargs):
        return [
            ValidationEvidence.fail_evidence(
                "DUMMY_FAIL", "Failed", 100, 90, 1.0, Severity.MAJOR
            )
        ]


@pytest.fixture
def test_registry():
    registry = RuleRegistry()
    registry.register("TEST_PASS", DummyPassRule)
    registry.register("TEST_FAIL", DummyFailRule)
    registry.register("TEST_BOTH", DummyPassRule)
    registry.register("TEST_BOTH", DummyFailRule)
    return registry


@pytest.fixture
def materiality_engine():
    return MaterialityEngine()


def test_audit_grade_validator_table(test_registry, materiality_engine):
    validator = AuditGradeValidator(test_registry, materiality_engine)

    # Test pass
    table_info = {
        "table_type": "TEST_PASS",
        "df": pd.DataFrame({"A": [1, 2]}),
        "code_col": "Code",
        "amount_cols": ["Amount"],
    }
    evidence = validator.validate_table(table_info)
    assert len(evidence) == 1
    assert evidence[0].is_material is False

    # Test fail
    table_info["table_type"] = "TEST_FAIL"
    evidence = validator.validate_table(table_info)
    assert len(evidence) == 1
    assert evidence[0].is_material is True

    # Test both
    table_info["table_type"] = "TEST_BOTH"
    evidence = validator.validate_table(table_info)
    assert len(evidence) == 2


def test_audit_grade_validator_model(test_registry, materiality_engine, monkeypatch):
    # Mock reconciliation to return 1 evidence
    def mock_reconcile(*args, **kwargs):
        return [ValidationEvidence.pass_evidence("RECON_MOCK", "Mock", 0, 0, 0)]

    validator = AuditGradeValidator(test_registry, materiality_engine)
    monkeypatch.setattr(validator.reconciler, "reconcile", mock_reconcile)

    model = FinancialModel()
    model.income_statements.append({"table_type": "TEST_PASS", "df": pd.DataFrame()})
    model.balance_sheets.append({"table_type": "TEST_FAIL", "df": pd.DataFrame()})

    all_evidence = validator.validate_model(model)

    # IS: 1 pass, BS: 1 fail, Recon: 1 mock pass
    assert len(all_evidence) == 3

    passes = [e for e in all_evidence if not e.is_material]
    fails = [e for e in all_evidence if e.is_material]

    assert len(passes) == 2
    assert len(fails) == 1
