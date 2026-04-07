"""
Thin adapter contracts for legacy baseline rule delegation.
"""

from dataclasses import dataclass


@dataclass
class LegacyRuleAdapter:
    source_file: str
    source_region: str
    current_module: str
    parity_status: str = "PORTED"
