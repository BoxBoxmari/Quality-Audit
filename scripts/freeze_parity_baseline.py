#!/usr/bin/env python3
"""
Copy aggregate_failures outputs into parity/baselines/ and write baseline_meta.json.

Typical flow:
  1. python scripts/run_regression_2docs.py ...  # writes reports/aggregate_failures.{json,csv}
  2. python scripts/freeze_parity_baseline.py

baseline_meta.json records frozen_at_utc, git commit, aggregate_schema_version (from JSON),
and relative paths to the copied artifacts under the baselines directory.
"""

from __future__ import annotations

import argparse
import json
import shutil
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path

_PROJECT_ROOT = Path(__file__).resolve().parent.parent
_DEFAULT_SOURCE_PREFIX = _PROJECT_ROOT / "reports" / "aggregate_failures"
_DEFAULT_DEST_DIR = _PROJECT_ROOT / "parity" / "baselines"
_META_SCHEMA_VERSION = "1"

_JSON_NAME = "aggregate_failures.json"
_CSV_NAME = "aggregate_failures.csv"


def _git_head(root: Path) -> str:
    try:
        out = subprocess.run(
            ["git", "rev-parse", "HEAD"],
            cwd=root,
            capture_output=True,
            text=True,
            check=True,
            timeout=30,
        )
        return out.stdout.strip() or "unknown"
    except (
        subprocess.CalledProcessError,
        FileNotFoundError,
        subprocess.TimeoutExpired,
    ):
        return "unknown"


def freeze_baseline(
    *,
    source_prefix: Path,
    dest_dir: Path,
    copy_csv: bool,
) -> dict:
    """
    Copy aggregate JSON (and optionally CSV) from source_prefix.* into dest_dir.

    Returns the baseline_meta document written to disk.
    """
    src_json = source_prefix.with_suffix(".json")
    if not src_json.is_file():
        raise FileNotFoundError(
            f"Missing aggregate JSON: {src_json}. Run run_regression_2docs.py or aggregate_failures.py first."
        )

    dest_dir.mkdir(parents=True, exist_ok=True)
    dest_json = dest_dir / _JSON_NAME
    shutil.copy2(src_json, dest_json)

    with open(dest_json, encoding="utf-8") as f:
        agg_doc = json.load(f)
    agg_schema = str(agg_doc.get("aggregate_schema_version", ""))

    meta: dict = {
        "baseline_meta_schema_version": _META_SCHEMA_VERSION,
        "frozen_at_utc": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
        "git_commit_hash": _git_head(_PROJECT_ROOT),
        "aggregate_schema_version": agg_schema,
        "files": {
            "aggregate_failures_json": _JSON_NAME,
        },
        "source_prefix": str(source_prefix.resolve()),
    }

    if copy_csv:
        src_csv = source_prefix.with_suffix(".csv")
        if not src_csv.is_file():
            raise FileNotFoundError(
                f"--copy-csv set but missing: {src_csv}",
            )
        shutil.copy2(src_csv, dest_dir / _CSV_NAME)
        meta["files"]["aggregate_failures_csv"] = _CSV_NAME

    meta_path = dest_dir / "baseline_meta.json"
    with open(meta_path, "w", encoding="utf-8") as f:
        json.dump(meta, f, indent=2, ensure_ascii=False)

    return meta


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Freeze aggregate_failures JSON/CSV into parity/baselines/ and write baseline_meta.json."
    )
    parser.add_argument(
        "--source-prefix",
        type=Path,
        default=_DEFAULT_SOURCE_PREFIX,
        help="Path prefix without extension (default: reports/aggregate_failures)",
    )
    parser.add_argument(
        "--dest-dir",
        type=Path,
        default=_DEFAULT_DEST_DIR,
        help="Baseline directory (default: parity/baselines)",
    )
    parser.add_argument(
        "--copy-csv",
        action="store_true",
        help="Also copy aggregate_failures.csv (must exist next to .json)",
    )
    args = parser.parse_args()

    source_prefix = (
        args.source_prefix
        if args.source_prefix.is_absolute()
        else _PROJECT_ROOT / args.source_prefix
    )
    dest_dir = (
        args.dest_dir if args.dest_dir.is_absolute() else _PROJECT_ROOT / args.dest_dir
    )

    try:
        meta = freeze_baseline(
            source_prefix=source_prefix,
            dest_dir=dest_dir,
            copy_csv=args.copy_csv,
        )
    except FileNotFoundError as e:
        print(str(e), file=sys.stderr)
        return 1

    print(f"Wrote {dest_dir / 'baseline_meta.json'}")
    print(f"Copied {dest_dir / _JSON_NAME}")
    if "aggregate_failures_csv" in meta.get("files", {}):
        print(f"Copied {dest_dir / _CSV_NAME}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
