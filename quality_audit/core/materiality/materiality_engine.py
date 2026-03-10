"""
Centralized dynamic materiality engine.

Design principles:
  - Tolerance scales with value magnitude (relative component).
  - A fixed floor prevents zero-tolerance on tiny values.
  - A ceiling prevents absurdly large tolerances.
  - Per-table-type profiles allow tighter checks on Balance Sheet
    vs. looser checks on note breakdowns.
  - All tolerance decisions flow through this single class.
"""

from __future__ import annotations


class MaterialityEngine:
    """Compute dynamic tolerance based on value magnitude and table type.

    Usage::

        engine = MaterialityEngine()
        tol = engine.compute(1_500_000, "INCOME_STATEMENT")
        # tol == max(1.0, 0.005 * 1_500_000) == 7_500.0

        if engine.is_material(diff=8_000, value=1_500_000, table_type="INCOME_STATEMENT"):
            # diff exceeds tolerance → material finding
    """

    # Absolute floor (minimum tolerance regardless of value)
    FLOOR_ABS: float = 1.0

    # Absolute ceiling (maximum tolerance regardless of value)
    CEILING_ABS: float = 1_000_000.0

    # Per-table-type relative thresholds (fraction of |value|)
    DEFAULT_PROFILE: dict[str, float] = {
        "BALANCE_SHEET": 0.001,  # 0.1%  — tightest
        "INCOME_STATEMENT": 0.005,  # 0.5%
        "CASH_FLOW": 0.005,  # 0.5%
        "EQUITY": 0.003,  # 0.3%
        "MOVEMENT": 0.002,  # 0.2%
        "NOTE_BREAKDOWN": 0.008,  # 0.8%  — matches legacy tolerance
        "TAX_NOTE": 0.005,  # 0.5%
        "FIXED_ASSET": 0.003,  # 0.3%
    }

    # Fallback relative threshold for unknown table types
    FALLBACK_RELATIVE: float = 0.008

    def __init__(
        self,
        *,
        floor_abs: float | None = None,
        ceiling_abs: float | None = None,
        profile: dict[str, float] | None = None,
    ) -> None:
        """Initialize with optional overrides.

        Args:
            floor_abs: Override minimum absolute tolerance.
            ceiling_abs: Override maximum absolute tolerance.
            profile: Override per-table-type relative thresholds.
        """
        self.floor_abs = floor_abs if floor_abs is not None else self.FLOOR_ABS
        self.ceiling_abs = ceiling_abs if ceiling_abs is not None else self.CEILING_ABS
        self.profile = profile if profile is not None else dict(self.DEFAULT_PROFILE)

    def compute(self, value: float, table_type: str) -> float:
        """Compute dynamic tolerance for a given value and table type.

        Formula::

            tolerance = clamp(floor, relative * |value|, ceiling)

        Args:
            value: The reference amount (e.g. expected total).
            table_type: Table classification string (e.g. "BALANCE_SHEET").

        Returns:
            Computed tolerance as a positive float.
        """
        relative = self.profile.get(table_type, self.FALLBACK_RELATIVE)
        raw = relative * abs(value)
        return max(self.floor_abs, min(raw, self.ceiling_abs))

    def is_material(self, diff: float, value: float, table_type: str) -> bool:
        """Check whether a difference is material.

        Args:
            diff: The difference (actual - expected).
            value: The reference amount for tolerance computation.
            table_type: Table classification string.

        Returns:
            True if ``|diff|`` exceeds the computed tolerance.
        """
        return abs(diff) > self.compute(value, table_type)

    def classify_severity(self, diff: float, value: float, table_type: str) -> str:
        """Classify severity based on diff magnitude relative to tolerance.

        Returns:
            One of "CRITICAL", "MAJOR", "MINOR", "INFO".
        """
        tolerance = self.compute(value, table_type)
        abs_diff = abs(diff)

        if abs_diff <= tolerance:
            return "INFO"

        # Ratio of diff to tolerance determines severity band
        ratio = abs_diff / tolerance if tolerance > 0 else float("inf")

        if ratio > 10.0:
            return "CRITICAL"
        elif ratio > 3.0:
            return "MAJOR"
        else:
            return "MINOR"
