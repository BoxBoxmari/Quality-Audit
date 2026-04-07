#!/usr/bin/env python3
"""
Lightweight MVP benchmark (throughput, p95 runtime, memory peak via tracemalloc).
"""

from __future__ import annotations

import argparse
import json
import statistics
import time
import tracemalloc
from datetime import datetime, timezone
from pathlib import Path

from run_regression_2docs import resolve_default_doc_paths, run_regression


def main() -> int:
    parser = argparse.ArgumentParser(description="Run MVP baseline benchmark.")
    parser.add_argument(
        "--root",
        type=Path,
        default=Path(__file__).resolve().parent.parent,
        help="Project root path.",
    )
    parser.add_argument(
        "--iterations",
        type=int,
        default=3,
        help="Benchmark iterations (default: 3).",
    )
    parser.add_argument(
        "--output-json",
        type=Path,
        default=Path("parity/baselines/perf_baseline.json"),
        help="Output JSON report path (relative to root if not absolute).",
    )
    args = parser.parse_args()

    root = args.root.resolve()
    docs = resolve_default_doc_paths(root)
    if len(docs) != 2:
        print("Insufficient fixture docs to run benchmark.")
        return 2

    out_json = args.output_json
    if not out_json.is_absolute():
        out_json = root / out_json
    out_json.parent.mkdir(parents=True, exist_ok=True)

    runtimes = []
    peak_mem_mb = []
    files_per_run = len(docs)

    for i in range(args.iterations):
        run_out = root / "results" / "benchmarks" / f"iter_{i+1}"
        run_out.mkdir(parents=True, exist_ok=True)
        tracemalloc.start()
        t0 = time.perf_counter()
        run_regression(
            doc_paths=list(docs),
            output_dir=run_out,
            run_aggregate=True,
            report_name=f"benchmark_{i+1}.md",
            output_prefix=f"bench_{i+1}",
        )
        elapsed = time.perf_counter() - t0
        _current, peak = tracemalloc.get_traced_memory()
        tracemalloc.stop()

        runtimes.append(elapsed)
        peak_mem_mb.append(peak / (1024 * 1024))

    p95 = (
        statistics.quantiles(runtimes, n=100)[94] if len(runtimes) >= 2 else runtimes[0]
    )
    throughput = (files_per_run * args.iterations) / sum(runtimes)

    payload = {
        "timestamp_utc": datetime.now(timezone.utc).isoformat(),
        "iterations": args.iterations,
        "files_per_iteration": files_per_run,
        "runtime_seconds": {
            "min": min(runtimes),
            "max": max(runtimes),
            "avg": statistics.mean(runtimes),
            "p95": p95,
        },
        "throughput_files_per_sec": throughput,
        "peak_memory_mb": {
            "min": min(peak_mem_mb),
            "max": max(peak_mem_mb),
            "avg": statistics.mean(peak_mem_mb),
        },
    }

    out_json.write_text(
        json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    print(json.dumps(payload, ensure_ascii=False, indent=2))
    print(f"Saved baseline to: {out_json}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
