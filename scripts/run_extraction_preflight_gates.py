#!/usr/bin/env python3
"""
Extraction preflight + parity regression gates.

Gate order:
1) Fixture availability gate (strict)
2) Deterministic regression tests for resolver/runtime contract
"""

from __future__ import annotations

import argparse
import subprocess
import sys
from pathlib import Path


def _run(cmd: list[str], cwd: Path) -> int:
    print(f"[gate] {' '.join(cmd)}")
    proc = subprocess.run(cmd, cwd=str(cwd))
    return proc.returncode


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Run extraction preflight and parity regression gates."
    )
    parser.add_argument(
        "--root",
        type=Path,
        default=Path(__file__).resolve().parent.parent,
        help="Project root path.",
    )
    parser.add_argument(
        "--skip-tests",
        action="store_true",
        help="Run only fixture preflight check.",
    )
    args = parser.parse_args()

    root = args.root.resolve()
    py = sys.executable

    steps = [
        [py, "scripts/check_regression_fixtures.py", "--strict"],
    ]
    if not args.skip_tests:
        steps.extend(
            [
                [
                    py,
                    "-m",
                    "pytest",
                    "-q",
                    "tests/test_run_regression_2docs_defaults.py",
                ],
                [py, "-m", "pytest", "-q", "tests/ui/test_ui_ctk_runtime_contract.py"],
                [py, "-m", "pytest", "-q", "tests/test_scrum11_contract_tests.py"],
            ]
        )

    for step in steps:
        rc = _run(step, cwd=root)
        if rc != 0:
            print(f"[gate] FAIL rc={rc}: {' '.join(step)}")
            return rc

    print("[gate] PASS: extraction preflight + parity regression")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
