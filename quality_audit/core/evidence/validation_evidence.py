"""
Structured validation evidence for audit-grade traceability.

Every assertion produces a ValidationEvidence object that records
what was checked, what was expected, what was found, whether the
difference is material, and full provenance metadata.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from .severity import Severity


@dataclass
class ValidationEvidence:
    """Single audit assertion result with full traceability.

    Attributes:
        rule_id: Unique identifier for the rule that produced this evidence.
        assertion_text: Human-readable description, e.g. "Code 20 = 01 - 11".
        expected: The value the rule expected.
        actual: The value found in the table.
        diff: ``actual - expected``.
        tolerance: Dynamic tolerance from MaterialityEngine.
        is_material: True if ``|diff| > tolerance``.
        severity: Finding severity (CRITICAL / MAJOR / MINOR / INFO).
        confidence: Confidence in the assertion (0.0–1.0).
        source_rows: Row indices involved in this assertion.
        source_cols: Column names involved in this assertion.
        table_type: Type of table this evidence belongs to.
        table_id: Optional table identifier for cross-referencing.
        metadata: Extensible dict for rule-specific context.
    """

    rule_id: str
    assertion_text: str
    expected: float
    actual: float
    diff: float
    tolerance: float
    is_material: bool
    severity: Severity
    confidence: float = 1.0
    source_rows: list[int] = field(default_factory=list)
    source_cols: list[str] = field(default_factory=list)
    table_type: str | None = None
    table_id: str | None = None
    metadata: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        """Serialize to dictionary for reporting and telemetry."""
        return {
            "rule_id": self.rule_id,
            "assertion_text": self.assertion_text,
            "expected": self.expected,
            "actual": self.actual,
            "diff": self.diff,
            "tolerance": self.tolerance,
            "is_material": self.is_material,
            "severity": self.severity.value,
            "confidence": self.confidence,
            "source_rows": self.source_rows,
            "source_cols": self.source_cols,
            "table_type": self.table_type,
            "table_id": self.table_id,
            **self.metadata,
        }

    def _apply_route_correction_metadata(self) -> ValidationEvidence:
        """Helper to append ROUTE_CORRECTION status to this evidence metadata.
        Used when FS rules skip narrative-style note tables.
        """
        self.metadata["reason_code"] = "ROUTE_CORRECTION"
        self.metadata["review_required"] = True
        return self

    @classmethod
    def pass_evidence(
        cls,
        rule_id: str,
        assertion_text: str,
        expected: float,
        actual: float,
        tolerance: float,
        *,
        confidence: float = 1.0,
        source_rows: list[int] | None = None,
        source_cols: list[str] | None = None,
        table_type: str | None = None,
        table_id: str | None = None,
    ) -> ValidationEvidence:
        """Factory for a passing assertion (diff within tolerance)."""
        diff = actual - expected
        return cls(
            rule_id=rule_id,
            assertion_text=assertion_text,
            expected=expected,
            actual=actual,
            diff=diff,
            tolerance=tolerance,
            is_material=False,
            severity=Severity.INFO,
            confidence=confidence,
            source_rows=source_rows or [],
            source_cols=source_cols or [],
            table_type=table_type,
            table_id=table_id,
        )

    @classmethod
    def fail_evidence(
        cls,
        rule_id: str,
        assertion_text: str,
        expected: float,
        actual: float,
        tolerance: float,
        severity: Severity,
        *,
        confidence: float = 1.0,
        source_rows: list[int] | None = None,
        source_cols: list[str] | None = None,
        table_type: str | None = None,
        table_id: str | None = None,
        metadata: dict[str, Any] | None = None,
    ) -> ValidationEvidence:
        """Factory for a failing assertion (diff exceeds tolerance)."""
        diff = actual - expected
        return cls(
            rule_id=rule_id,
            assertion_text=assertion_text,
            expected=expected,
            actual=actual,
            diff=diff,
            tolerance=tolerance,
            is_material=True,
            severity=severity,
            confidence=confidence,
            source_rows=source_rows or [],
            source_cols=source_cols or [],
            table_type=table_type,
            table_id=table_id,
            metadata=metadata or {},
        )

    @classmethod
    def warn_evidence(
        cls,
        rule_id: str,
        assertion_text: str,
        *,
        reason_code: str,
        expected: float = 0.0,
        actual: float = 0.0,
        tolerance: float = 0.0,
        confidence: float = 1.0,
        source_rows: list[int] | None = None,
        source_cols: list[str] | None = None,
        table_type: str | None = None,
        table_id: str | None = None,
        metadata: dict[str, Any] | None = None,
    ) -> ValidationEvidence:
        """Factory for a WARN assertion (ambiguity / review required).

        Caller must set metadata.reason_code from WARN_REASON_* constants.
        Status mapping uses reason_code to set status_enum to WARN.
        """
        meta = dict(metadata or {})
        meta["reason_code"] = reason_code
        meta["review_required"] = True
        return cls(
            rule_id=rule_id,
            assertion_text=assertion_text,
            expected=expected,
            actual=actual,
            diff=0.0,
            tolerance=tolerance,
            is_material=False,
            severity=Severity.INFO,
            confidence=confidence,
            source_rows=source_rows or [],
            source_cols=source_cols or [],
            table_type=table_type,
            table_id=table_id,
            metadata=meta,
        )
