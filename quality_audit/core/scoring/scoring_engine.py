"""
ScoringEngine for generating quantitative audit grades based on evidence.
"""

from __future__ import annotations

import logging

from quality_audit.core.evidence import Severity, ValidationEvidence

logger = logging.getLogger(__name__)


class ScoringEngine:
    """Calculates a deterministic 0-100 audit score based on validation evidence."""

    def __init__(self, base_score: float = 100.0) -> None:
        self.base_score = base_score

    def evaluate_score(self, evidence_list: list[ValidationEvidence]) -> float:
        """
        Calculate the score.

        Deductions:
            - CRITICAL: -20.0
            - MAJOR: -5.0
            - MINOR: -1.0
            - INFO: 0.0
        """
        score = self.base_score

        for ev in evidence_list:
            if not ev.is_material:
                continue

            if ev.severity == Severity.CRITICAL:
                score -= 20.0
            elif ev.severity == Severity.MAJOR:
                score -= 5.0
            elif ev.severity == Severity.MINOR:
                score -= 1.0

        return max(0.0, score)
