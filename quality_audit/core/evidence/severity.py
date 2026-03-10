"""
Severity levels for audit validation findings.

Used by ValidationEvidence and ScoringEngine to classify
the impact of each validation result.
"""

from enum import Enum


class Severity(Enum):
    """Audit finding severity level.

    Ordered from highest impact to lowest:
    - CRITICAL: Material misstatement, blocks sign-off
    - MAJOR: Significant error requiring correction
    - MINOR: Immaterial difference, note for review
    - INFO: Informational, no action required
    """

    CRITICAL = "CRITICAL"
    MAJOR = "MAJOR"
    MINOR = "MINOR"
    INFO = "INFO"

    @property
    def deduction(self) -> int:
        """Score deduction for this severity level."""
        return _DEDUCTION_MAP[self]

    def __lt__(self, other: "Severity") -> bool:
        if not isinstance(other, Severity):
            return NotImplemented
        return _ORDER[self] < _ORDER[other]

    def __le__(self, other: "Severity") -> bool:
        if not isinstance(other, Severity):
            return NotImplemented
        return _ORDER[self] <= _ORDER[other]


# Internal ordering: higher number = more severe
_ORDER = {
    Severity.INFO: 0,
    Severity.MINOR: 1,
    Severity.MAJOR: 2,
    Severity.CRITICAL: 3,
}

_DEDUCTION_MAP = {
    Severity.CRITICAL: 25,
    Severity.MAJOR: 10,
    Severity.MINOR: 3,
    Severity.INFO: 0,
}
