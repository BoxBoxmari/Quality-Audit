"""
Abstract base class for audit-grade validation rules.

Each concrete rule class encapsulates a specific set of assertions
for a particular table type (e.g. IncomeStatementRules, MovementRules).
Rules produce ValidationEvidence objects and never return bare strings.
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from typing import TYPE_CHECKING, Any

import pandas as pd

from ..evidence import Severity, ValidationEvidence

if TYPE_CHECKING:
    import pandas as pd

    from ..materiality import MaterialityEngine
    from ..model.statement_model_builder import StatementModel


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
    table_types: list[str] = []

    @abstractmethod
    def evaluate(
        self,
        df: pd.DataFrame,
        *,
        materiality: MaterialityEngine,
        table_type: str,
        table_id: str | None = None,
        code_col: str | None = None,
        amount_cols: list[str] | None = None,
    ) -> list[ValidationEvidence]:
        """Run assertions against the table and return evidence."""
        ...

    def evaluate_model(
        self, model: StatementModel, *, materiality: MaterialityEngine, **kwargs
    ) -> list[ValidationEvidence]:
        """Run assertions against a full StatementModel and return evidence.

        Subclasses that operate on multi-table statements (like Cash Flow)
        should override this method.
        """
        raise NotImplementedError(
            "This rule does not support statement-level evaluation."
        )

    def _parse_float(self, val: Any) -> float:
        """Robustly convert a cell value (string, int, float) to float."""
        if pd.isna(val) or val is None:
            return 0.0
        if isinstance(val, (int, float)):
            return float(val)

        s = str(val).strip()
        if not s:
            return 0.0

        # Handle parentheses for negatives (e.g. "(1,234)" -> "-1,234")
        is_negative = False
        if s.startswith("(") and s.endswith(")"):
            is_negative = True
            s = s[1:-1].strip()
        elif s.startswith("-"):
            is_negative = True
            s = s[1:].strip()

        # Remove thousands separators (commas or spaces)
        s = s.replace(",", "").replace(" ", "")

        try:
            res = float(s)
            return -res if is_negative else res
        except ValueError:
            return 0.0

    def _make_evidence(
        self,
        assertion_text: str,
        expected: float,
        actual: float,
        tolerance: float,
        *,
        table_type: str,
        table_id: str | None = None,
        source_rows: list[int] | None = None,
        source_cols: list[str] | None = None,
        severity_override: Severity | None = None,
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
