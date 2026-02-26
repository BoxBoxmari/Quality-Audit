"""
SCRUM-7 P1: Run-to-Run Diff Engine.

Compares current audit results with previous run output to identify:
- New FAILs (regression)
- Resolved FAILs (improvement)
- Unchanged findings
- Changed severity/confidence
"""

import json
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, cast


@dataclass
class DiffResult:
    """Result of comparing two audit runs."""

    new_fails: list[dict[str, Any]] = field(default_factory=list)
    resolved: list[dict[str, Any]] = field(default_factory=list)
    unchanged: list[dict[str, Any]] = field(default_factory=list)
    changed: list[dict[str, Any]] = field(default_factory=list)
    summary: dict[str, int] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return {
            "new_fails": self.new_fails,
            "resolved": self.resolved,
            "unchanged": self.unchanged,
            "changed": self.changed,
            "summary": self.summary,
        }


class DiffEngine:
    """
    Compares current audit results with a previous output file.

    Usage:
        engine = DiffEngine()
        diff = engine.compare(current_results, previous_path)
    """

    def __init__(self):
        self._key_fields = ("rule_id", "context.heading")

    def _get_finding_key(self, finding: dict) -> tuple[str, str]:
        """
        Generate a unique key for a finding based on rule_id and table heading.

        Args:
            finding: Validation result dictionary

        Returns:
            Tuple of (rule_id, heading) as unique key
        """
        rule_id = finding.get("rule_id", "UNKNOWN")
        context = finding.get("context", {})
        heading = context.get("heading", "Unknown")
        return (rule_id, heading)

    def _load_previous_results(self, path: Path) -> list[dict]:
        """
        Load previous audit results from JSON summary file.

        Args:
            path: Path to previous output (expects .json or .xlsx with sidecar .json)

        Returns:
            List of validation result dictionaries
        """
        json_path = path
        if path.suffix.lower() == ".xlsx":
            # Look for sidecar JSON file
            json_path = path.with_suffix(".json")

        if not json_path.exists():
            return []

        try:
            with open(json_path, encoding="utf-8") as f:
                data = json.load(f)
                # Support both direct list and wrapped format
                if isinstance(data, list):
                    return cast(list[dict[str, Any]], data)
                elif isinstance(data, dict) and "results" in data:
                    return cast(list[dict[str, Any]], data["results"])
                return []
        except (OSError, json.JSONDecodeError):
            return []

    def compare(
        self,
        current_results: list[dict],
        previous_path: Path | None = None,
    ) -> DiffResult:
        """
        Compare current results with previous run.

        Args:
            current_results: Current audit results
            previous_path: Path to previous output file

        Returns:
            DiffResult with categorized findings
        """
        diff = DiffResult()

        if not previous_path or not previous_path.exists():
            # No previous run - all findings are "new"
            actionable = [
                r
                for r in current_results
                if r.get("status_enum")
                in [
                    "FAIL",
                    "ERROR",
                    "WARN",
                    "FAIL_TOOL_EXTRACT",
                    "FAIL_TOOL_LOGIC",
                    "FAIL_DATA",
                ]
            ]
            diff.new_fails = actionable
            diff.summary = {
                "new_fails": len(actionable),
                "resolved": 0,
                "unchanged": 0,
                "changed": 0,
                "first_run": True,
            }
            return diff

        previous_results = self._load_previous_results(previous_path)

        # Build lookup maps
        fail_warn_statuses = [
            "FAIL",
            "ERROR",
            "WARN",
            "FAIL_TOOL_EXTRACT",
            "FAIL_TOOL_LOGIC",
            "FAIL_DATA",
        ]
        curr_actionable = {
            self._get_finding_key(r): r
            for r in current_results
            if r.get("status_enum") in fail_warn_statuses
        }
        prev_actionable = {
            self._get_finding_key(r): r
            for r in previous_results
            if r.get("status_enum") in fail_warn_statuses
        }

        curr_keys = set(curr_actionable.keys())
        prev_keys = set(prev_actionable.keys())

        # New FAILs: in current but not in previous
        for key in curr_keys - prev_keys:
            finding = curr_actionable[key].copy()
            finding["diff_status"] = "NEW"
            diff.new_fails.append(finding)

        # Resolved: in previous but not in current
        for key in prev_keys - curr_keys:
            finding = prev_actionable[key].copy()
            finding["diff_status"] = "RESOLVED"
            diff.resolved.append(finding)

        # Both: check for changes
        for key in curr_keys & prev_keys:
            curr_finding = curr_actionable[key]
            prev_finding = prev_actionable[key]

            # Check if severity or confidence changed
            curr_sev = curr_finding.get("severity")
            prev_sev = prev_finding.get("severity")
            curr_conf = curr_finding.get("confidence")
            prev_conf = prev_finding.get("confidence")

            if curr_sev != prev_sev or curr_conf != prev_conf:
                changed_entry = curr_finding.copy()
                changed_entry["diff_status"] = "CHANGED"
                changed_entry["previous_severity"] = prev_sev
                changed_entry["previous_confidence"] = prev_conf
                diff.changed.append(changed_entry)
            else:
                unchanged_entry = curr_finding.copy()
                unchanged_entry["diff_status"] = "UNCHANGED"
                diff.unchanged.append(unchanged_entry)

        diff.summary = {
            "new_fails": len(diff.new_fails),
            "resolved": len(diff.resolved),
            "unchanged": len(diff.unchanged),
            "changed": len(diff.changed),
            "first_run": False,
        }

        return diff
