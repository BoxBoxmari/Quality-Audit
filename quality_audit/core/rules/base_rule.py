"""
Abstract base class for audit-grade validation rules.

Each concrete rule class encapsulates a specific set of assertions
for a particular table type (e.g. IncomeStatementRules, MovementRules).
Rules produce ValidationEvidence objects and never return bare strings.
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from typing import TYPE_CHECKING, List, Optional

from ..evidence import Severity, ValidationEvidence

if TYPE_CHECKING:
    import pandas as pd

    from ..materiality import MaterialityEngine


class AuditRule(ABC):
    """Abstract base for a typed audit rule.

    Subclasses must implement :meth:`evaluate` which receives the table
    data and returns a list of :class:`ValidationEvidence` objects — one
    per assertion checked.

    Attributes:
        rule_id: Unique identifier for this rule (e.g. "IS_FORMULA_20").
        description: Human-readable description.
        severity_default: Default severity when an assertion fails.
        table_types: List of table types this rule applies to.
    """

    rule_id: str = "UNSET"
    description: str = ""
    severity_default: Severity = Severity.MAJOR
    table_types: List[str] = []

    @abstractmethod
    def evaluate(
        self,
        df: pd.DataFrame,
        *,
        materiality: MaterialityEngine,
        table_type: str,
        table_id: Optional[str] = None,
        code_col: Optional[str] = None,
        amount_cols: Optional[List[str]] = None,
    ) -> List[ValidationEvidence]:
        """Run assertions against the table and return evidence.

        Args:
            df: Table DataFrame (already header-promoted, normalized).
            materiality: MaterialityEngine instance for tolerance computation.
            table_type: Classified table type string.
            table_id: Optional identifier for this table.
            code_col: Name of the code column (if detected).
            amount_cols: Names of numeric amount columns.

        Returns:
            List of ValidationEvidence objects (one per assertion).
            Empty list means all assertions passed or were not applicable.
        """
        ...

    def _make_evidence(
        self,
        assertion_text: str,
        expected: float,
        actual: float,
        tolerance: float,
        *,
        table_type: str,
        table_id: Optional[str] = None,
        source_rows: Optional[List[int]] = None,
        source_cols: Optional[List[str]] = None,
        severity_override: Optional[Severity] = None,
        confidence: float = 1.0,
    ) -> ValidationEvidence:
        """Helper to build a ValidationEvidence from assertion inputs.

        Automatically determines ``is_material`` and picks severity.
        """
        diff = actual - expected
        is_material = abs(diff) > tolerance
        severity = self.severity_default if is_material else Severity.INFO
        if severity_override is not None and is_material:
            severity = severity_override

        return ValidationEvidence(
            rule_id=self.rule_id,
            assertion_text=assertion_text,
            expected=expected,
            actual=actual,
            diff=diff,
            tolerance=tolerance,
            is_material=is_material,
            severity=severity,
            confidence=confidence,
            source_rows=source_rows or [],
            source_cols=source_cols or [],
            table_type=table_type,
            table_id=table_id,
        )
