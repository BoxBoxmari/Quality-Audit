"""
Cross-table reconciliation for note tables vs FS line items.

Ticket 7: After all tables are validated, this service reconciles
note table totals against the corresponding FS line items stored
in cross_check_cache.
"""

import logging
from dataclasses import dataclass, field
from typing import Dict, List, Optional

from quality_audit.core.cache_manager import cross_check_cache
from quality_audit.utils.numeric_utils import compare_amounts

logger = logging.getLogger(__name__)


@dataclass
class ReconciliationItem:
    """Single reconciliation result between a note table and an FS line item."""

    note_heading: str
    fs_account: str
    note_total_cy: Optional[float]
    note_total_py: Optional[float]
    fs_value_cy: Optional[float]
    fs_value_py: Optional[float]
    delta_cy: Optional[float]
    delta_py: Optional[float]
    status: str  # MATCH | MISMATCH | UNMATCHED


@dataclass
class ReconciliationReport:
    """Report containing all reconciliation results."""

    items: List[ReconciliationItem] = field(default_factory=list)
    match_count: int = 0
    mismatch_count: int = 0
    unmatched_count: int = 0

    def summary(self) -> Dict[str, int]:
        return {
            "total": len(self.items),
            "match": self.match_count,
            "mismatch": self.mismatch_count,
            "unmatched": self.unmatched_count,
        }


class FinancialReconciliationService:
    """Reconcile note table totals against FS cache entries."""

    def reconcile(
        self,
        note_results: Dict[str, dict],
        abs_tol: float = 1.0,
        rel_tol: float = 0.01,
    ) -> ReconciliationReport:
        """
        Reconcile note table totals against FS line items in cache.

        Args:
            note_results: Dict of {heading -> validation_context} where
                validation_context may contain 'total_row_value_cy' and
                'total_row_value_py' from the validator.
            abs_tol: Absolute tolerance for matching.
            rel_tol: Relative tolerance for matching.

        Returns:
            ReconciliationReport with per-note reconciliation items.
        """
        report = ReconciliationReport()

        for heading, ctx in note_results.items():
            heading_lower = heading.lower().strip()
            note_cy = ctx.get("total_row_value_cy")
            note_py = ctx.get("total_row_value_py")

            # Look up FS cache entry
            fs_entry = cross_check_cache.get(heading_lower)
            if fs_entry is None:
                item = ReconciliationItem(
                    note_heading=heading,
                    fs_account=heading_lower,
                    note_total_cy=note_cy,
                    note_total_py=note_py,
                    fs_value_cy=None,
                    fs_value_py=None,
                    delta_cy=None,
                    delta_py=None,
                    status="UNMATCHED",
                )
                report.items.append(item)
                report.unmatched_count += 1
                logger.debug(
                    "Reconciliation: UNMATCHED note '%s' (no FS cache entry)",
                    heading,
                )
                continue

            fs_cy, fs_py = fs_entry
            delta_cy = None
            delta_py = None
            cy_ok = True
            py_ok = True

            if note_cy is not None and fs_cy is not None:
                cy_ok, delta_cy, _, _ = compare_amounts(
                    note_cy, fs_cy, abs_tol=abs_tol, rel_tol=rel_tol
                )
            elif note_cy is not None or fs_cy is not None:
                cy_ok = False
                delta_cy = None

            if note_py is not None and fs_py is not None:
                py_ok, delta_py, _, _ = compare_amounts(
                    note_py, fs_py, abs_tol=abs_tol, rel_tol=rel_tol
                )
            elif note_py is not None or fs_py is not None:
                py_ok = False
                delta_py = None

            status = "MATCH" if (cy_ok and py_ok) else "MISMATCH"

            item = ReconciliationItem(
                note_heading=heading,
                fs_account=heading_lower,
                note_total_cy=note_cy,
                note_total_py=note_py,
                fs_value_cy=fs_cy,
                fs_value_py=fs_py,
                delta_cy=delta_cy,
                delta_py=delta_py,
                status=status,
            )
            report.items.append(item)
            if status == "MATCH":
                report.match_count += 1
            else:
                report.mismatch_count += 1

            logger.info(
                "Reconciliation: %s note='%s' fs_cy=%.2f note_cy=%s delta_cy=%s",
                status,
                heading,
                fs_cy if fs_cy is not None else 0,
                note_cy,
                delta_cy,
            )

        return report
