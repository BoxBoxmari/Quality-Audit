"""
Baseline provenance metadata for imported legacy rule clusters.
"""

from dataclasses import dataclass

BASELINE_SOURCES = (
    "legacy/main.py",
    "legacy/Quality Audit.py",
)


@dataclass(frozen=True)
class RuleProvenance:
    source_file: str
    source_region: str
    current_module: str
    parity_status: str = "PORTED"
