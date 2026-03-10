import pytest

from quality_audit.core.evidence import Severity, ValidationEvidence
from quality_audit.core.scoring.scoring_engine import ScoringEngine


def test_scoring_engine_perfect_score():
    engine = ScoringEngine()

    evidence_list = [
        ValidationEvidence.pass_evidence("RULE_1", "Desc", 100, 100, 1.0),
        ValidationEvidence.pass_evidence("RULE_2", "Desc", 100, 100, 1.0),
    ]

    score = engine.evaluate_score(evidence_list)
    assert score == 100.0


def test_scoring_engine_with_deductions():
    engine = ScoringEngine()

    evidence_list = [
        # Pass (0 deduction)
        ValidationEvidence.pass_evidence("RULE_1", "Desc", 100, 100, 1.0),
        # Critical (-20)
        ValidationEvidence.fail_evidence(
            "RULE_2", "Desc", 100, 0, 1.0, Severity.CRITICAL
        ),
        # Major (-5)
        ValidationEvidence.fail_evidence(
            "RULE_3", "Desc", 100, 50, 1.0, Severity.MAJOR
        ),
        # Minor (-1)
        ValidationEvidence.fail_evidence(
            "RULE_4", "Desc", 100, 95, 1.0, Severity.MINOR
        ),
        # Minor (-1)
        ValidationEvidence.fail_evidence(
            "RULE_5", "Desc", 100, 95, 1.0, Severity.MINOR
        ),
    ]

    # 100 - 20 - 5 - 1 - 1 = 73
    score = engine.evaluate_score(evidence_list)
    assert score == 73.0


def test_scoring_engine_floor_zero():
    engine = ScoringEngine(base_score=10.0)

    evidence_list = [
        # Critical (-20)
        ValidationEvidence.fail_evidence(
            "RULE_1", "Desc", 100, 0, 1.0, Severity.CRITICAL
        ),
    ]

    # 10 - 20 = -10 -> max(0, -10) = 0
    score = engine.evaluate_score(evidence_list)
    assert score == 0.0
