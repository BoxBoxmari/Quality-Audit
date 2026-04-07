#!/usr/bin/env python3
"""
Preflight check for 2-DOCX regression fixtures.

This script validates whether the default fixture resolver can find a complete
pair of regression DOCX files in a clean clone.
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

_this_dir = Path(__file__).resolve().parent
_project_root = _this_dir.parent
if str(_this_dir) not in sys.path:
    sys.path.insert(0, str(_this_dir))
if str(_project_root) not in sys.path:
    sys.path.insert(0, str(_project_root))

from run_regression_2docs import resolve_default_doc_paths  # noqa: E402


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Check default regression fixture availability (CP + CJCGV DOCX)."
    )
    parser.add_argument(
        "--root",
        type=Path,
        default=_project_root,
        help="Project root directory (default: repository root).",
    )
    parser.add_argument(
        "--json",
        action="store_true",
        help="Emit machine-readable JSON output.",
    )
    parser.add_argument(
        "--strict",
        action="store_true",
        help="Return non-zero if fixture pair is missing.",
    )
    args = parser.parse_args()

    root = args.root.resolve()
    resolved = resolve_default_doc_paths(root)
    ok = len(resolved) == 2

    payload = {
        "root": str(root),
        "ok": ok,
        "doc_paths": [str(p) for p in resolved],
        "search_order": [
            str(root / "data"),
            str(root / "tests" / "test_data"),
            str(root / "tests" / "data"),
            str(root / "test_data"),
        ],
    }

    if args.json:
        print(json.dumps(payload, ensure_ascii=False, indent=2))
    else:
        print(f"root: {payload['root']}")
        print("search_order:")
        for entry in payload["search_order"]:
            print(f"  - {entry}")
        if ok:
            print("status: OK (found fixture pair)")
            print(f"cp_docx: {payload['doc_paths'][0]}")
            print(f"cjcgv_docx: {payload['doc_paths'][1]}")
        else:
            print("status: MISSING (fixture pair not found)")
            print(
                "hint: place both DOCX files in the same directory from search_order."
            )

    if args.strict and not ok:
        return 2
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
