"""
Breakdown Rules.

Validates breakdown note tables: Sum(detail_rows) = total_row per column.
"""

from __future__ import annotations

import logging

from quality_audit.core.evidence.severity import Severity
from quality_audit.core.rules.sum_within_tolerance import SumWithinToleranceRule

logger = logging.getLogger(__name__)


class BreakdownRules(SumWithinToleranceRule):
    """
    Validates note breakdown tables column-by-column.
    """

    rule_id = "NOTE_BREAKDOWN_TOTALS"
    description = "Kiểm tra tổng cộng phân tích chi tiết: Tổng các số dư = Dòng cộng"
    severity_default = Severity.MAJOR
    table_types = ["GENERIC_NOTE", "TAX_NOTE"]
