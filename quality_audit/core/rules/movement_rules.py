"""
Movement Rules.

Validates roll-forward tables: Opening Balance + Movements = Closing Balance.
"""

from __future__ import annotations

import logging

from quality_audit.core.evidence.severity import Severity
from quality_audit.core.rules.movement_equation import MovementEquationRule

logger = logging.getLogger(__name__)


class MovementRules(MovementEquationRule):
    """
    Validates rollforward tables column-by-column.
    """

    rule_id = "MOVEMENT_ROLLFORWARD"
    description = "Kiểm tra biến động: Đầu kỳ + Phát sinh = Cuối kỳ"
    severity_default = Severity.MAJOR
    table_types = ["GENERIC_NOTE", "FS_EQUITY"]
