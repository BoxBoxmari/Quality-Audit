#!/usr/bin/env python3
"""
P0: Run Quality Audit pipeline on two DOCX files for baseline/regression.

Accepts paths via CLI (positional doc1, doc2). If not provided, resolves defaults
via ``resolve_default_doc_paths(project_root)``: searches, in order,
``data/``, ``tests/test_data``, ``tests/data``, ``test_data/`` for a complete
pair (CP Vietnam exact name; CJCGV with alias preference, case-insensitive
``.docx``). Returns ``[]`` if no single directory contains both files.

Writes reports/baseline_2docs.md and optionally runs aggregate_failures on outputs.
"""

import argparse
import logging
import sys
from datetime import datetime, timezone
from pathlib import Path

# Add project root to path when run as script
_project_root = Path(__file__).resolve().parent.parent
if str(_project_root) not in sys.path:
    sys.path.insert(0, str(_project_root))

# Configure logging to ensure INFO level logs are visible
logging.basicConfig(
    level=logging.INFO,
    format="%(levelname)s - %(name)s - %(message)s",
    stream=sys.stderr,
)
logging.getLogger("quality_audit").setLevel(logging.INFO)

from quality_audit.config.tax_rate import TaxRateConfig  # noqa: E402
from quality_audit.core.cache_manager import AuditContext  # noqa: E402
from quality_audit.services.audit_service import AuditService  # noqa: E402

# Default fixture basenames (CP exact; CJCGV: prefer no space before extension)
_CP_DOCX_NAME = "CP Vietnam-FS2018-Consol-EN.docx"
_CJCGV_ALIAS_PRIMARY = "CJCGV-FS2018-EN- v2.docx"
_CJCGV_ALIAS_SPACE_BEFORE_EXT = "CJCGV-FS2018-EN- v2 .docx"
_CJCGV_STEM_PRIMARY = Path(_CJCGV_ALIAS_PRIMARY).stem
_CJCGV_STEM_SPACE = Path(_CJCGV_ALIAS_SPACE_BEFORE_EXT).stem


def _is_docx_file(path: Path) -> bool:
    return path.is_file() and path.suffix.lower() == ".docx"


def _find_cp_docx(base: Path) -> Path | None:
    """Resolve CP fixture under ``base``: exact basename, else scan (``.docx`` case-insensitive)."""
    exact = base / _CP_DOCX_NAME
    if exact.is_file():
        return exact
    expected_stem = Path(_CP_DOCX_NAME).stem
    if not base.is_dir():
        return None
    for candidate in base.iterdir():
        if not _is_docx_file(candidate):
            continue
        if candidate.stem == expected_stem:
            return candidate
    return None


def _find_cjcgv_docx(base: Path) -> Path | None:
    """
    Resolve CJCGV under ``base``: prefer ``CJCGV-FS2018-EN- v2.docx``, then ``… v2 .docx``;
    extension matched case-insensitively; scan directory if exact paths missing.
    """
    if not base.is_dir():
        return None
    for name in (_CJCGV_ALIAS_PRIMARY, _CJCGV_ALIAS_SPACE_BEFORE_EXT):
        p = base / name
        if p.is_file():
            return p
    # Case-insensitive extension: try same stems with any .docx spelling
    for candidate in base.iterdir():
        if not _is_docx_file(candidate):
            continue
        if (
            candidate.name == _CJCGV_ALIAS_PRIMARY
            or candidate.stem == _CJCGV_STEM_PRIMARY
        ):
            return candidate
    for candidate in base.iterdir():
        if not _is_docx_file(candidate):
            continue
        if (
            candidate.name == _CJCGV_ALIAS_SPACE_BEFORE_EXT
            or candidate.stem == _CJCGV_STEM_SPACE
        ):
            return candidate
    return None


def resolve_default_doc_paths(root: Path) -> list[Path]:
    """
    Return ``[cp_path, cjcgv_path]`` both ``.resolve()``'d, or ``[]`` if no directory has both.

    Search order (relative to ``root``): ``data/``, ``tests/test_data``, ``tests/data``,
    ``test_data/``. Both files must live in the same base directory.
    """
    candidates = [
        root / "data",
        root / "tests" / "test_data",
        root / "tests" / "data",
        root / "test_data",
    ]
    for base in candidates:
        if not base.is_dir():
            continue
        cp = _find_cp_docx(base)
        cj = _find_cjcgv_docx(base)
        if cp is not None and cj is not None:
            return [cp.resolve(), cj.resolve()]
    return []


def _default_doc_paths() -> list[Path]:
    """Resolve default 2 DOCX paths via :func:`resolve_default_doc_paths`."""
    return resolve_default_doc_paths(_project_root)


def _default_doc_resolution_hint() -> str:
    """Human-readable hint when CLI omits paths and :func:`resolve_default_doc_paths` returns []."""
    return (
        "Không tìm thấy cặp DOCX mặc định trong cùng một thư mục (theo thứ tự ưu tiên từ root "
        "project): data/ → tests/test_data/ → tests/data/ → test_data/.\n"
        f"  • CP: đúng tên `{_CP_DOCX_NAME}` (hoặc cùng stem, phần mở rộng .docx không phân biệt hoa thường).\n"
        f"  • CJCGV: ưu tiên `{_CJCGV_ALIAS_PRIMARY}`, sau đó `{_CJCGV_ALIAS_SPACE_BEFORE_EXT}` "
        "(có thể quét thư mục nếu không khớp đường dẫn tuyệt đối).\n"
        "Hoặc truyền đủ 2 đường dẫn: python scripts/run_regression_2docs.py <doc1.docx> <doc2.docx>"
    )


def run_regression(
    doc_paths: list[Path],
    output_dir: Path,
    run_aggregate: bool = True,
    report_name: str = "baseline_2docs.md",
    output_prefix: str = "baseline",
) -> dict:
    """
    Run audit on each DOCX and write report.

    Returns:
        Dict with keys: doc_paths, results (per-doc), output_xlsx_paths, report_path,
        aggregate_path (if run_aggregate), timestamp.
    """
    output_dir.mkdir(parents=True, exist_ok=True)
    # Headless: use fixed tax rate so no input() is ever called
    ctx = AuditContext(
        tax_rate_config=TaxRateConfig(mode="all", all_rate=0.25),
        base_path=_project_root,
    )
    audit_service = AuditService(context=ctx)
    results = []
    output_xlsx_paths = []

    for i, doc_path in enumerate(doc_paths):
        if not doc_path.exists():
            results.append(
                {
                    "doc_path": str(doc_path),
                    "success": False,
                    "error": "File not found",
                    "tables_processed": 0,
                    "output_path": None,
                }
            )
            continue
        stem = doc_path.stem.replace(" ", "_")[:50]
        excel_path = output_dir / f"{output_prefix}_{i + 1}_{stem}.xlsx"
        result = audit_service.audit_document(str(doc_path), str(excel_path))
        results.append(
            {
                "doc_path": str(doc_path),
                "success": result.get("success", False),
                "error": result.get("error"),
                "tables_processed": result.get("tables_processed", 0),
                "output_path": str(excel_path) if result.get("success") else None,
            }
        )
        if result.get("success") and result.get("output_path"):
            output_xlsx_paths.append(Path(result["output_path"]))

    timestamp = datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")
    report_path = output_dir / report_name
    title = (
        "After 2 DOCX Report"
        if "after" in report_name.lower()
        else "Baseline 2 DOCX Report"
    )
    report_lines = [
        f"# {title}",
        "",
        f"**Generated:** {timestamp}",
        "",
        "## Document paths",
        "",
    ]
    for p in doc_paths:
        report_lines.append(f"- `{p}`")
    report_lines.extend(
        [
            "",
            "## Per-document results",
            "",
            "| Doc | Success | Tables | Output XLSX |",
            "|-----|---------|--------|-------------|",
        ]
    )
    for i, r in enumerate(results):
        out = r.get("output_path") or "-"
        report_lines.append(
            f"| {i + 1} | {r.get('success', False)} | {r.get('tables_processed', 0)} | {out} |"
        )
    report_lines.extend(
        [
            "",
            "## Aggregate",
            "",
            "Run `python scripts/aggregate_failures.py <xlsx1> [xlsx2] ...` to produce "
            "failure aggregates (validator_type, failure_reason_code, rule_id, etc.).",
            "",
        ]
    )
    report_path.write_text("\n".join(report_lines), encoding="utf-8")

    aggregate_path = None
    if run_aggregate and output_xlsx_paths:
        import subprocess

        aggregate_path = output_dir / "aggregate_failures"
        try:
            subprocess.run(
                [
                    sys.executable,
                    str(_project_root / "scripts" / "aggregate_failures.py"),
                    *[str(p) for p in output_xlsx_paths],
                    "-o",
                    str(aggregate_path),
                ],
                cwd=str(_project_root),
                check=True,
                capture_output=True,
            )
        except subprocess.CalledProcessError as e:
            report_lines.append(
                f"\n**Aggregate run error:** {e.stderr and e.stderr.decode() or str(e)}\n"
            )
            report_path.write_text("\n".join(report_lines), encoding="utf-8")
        except Exception as e:
            report_lines.append(f"\n**Aggregate run error:** {e}\n")
            report_path.write_text("\n".join(report_lines), encoding="utf-8")

    return {
        "doc_paths": [str(p) for p in doc_paths],
        "results": results,
        "output_xlsx_paths": [str(p) for p in output_xlsx_paths],
        "report_path": str(report_path),
        "aggregate_path": str(aggregate_path) if aggregate_path else None,
        "timestamp": timestamp,
    }


def main() -> int:
    parser = argparse.ArgumentParser(
        description=(
            "P0: Run Quality Audit on 2 DOCX files for baseline/regression. "
            "Omit both positional args to auto-resolve defaults via resolve_default_doc_paths: "
            "search data/, tests/test_data/, tests/data/, test_data/ (same directory must contain both)."
        )
    )
    parser.add_argument(
        "doc1",
        nargs="?",
        type=Path,
        help=(
            "First DOCX. Omit both doc1 and doc2 to use defaults (CP exact name; CJCGV alias order) "
            "from data/ → tests/test_data/ → tests/data/ → test_data/"
        ),
    )
    parser.add_argument(
        "doc2",
        nargs="?",
        type=Path,
        help="Second DOCX (omit with doc1 only if you intend to rely on defaults for the full pair)",
    )
    parser.add_argument(
        "--output-dir",
        type=Path,
        default=_project_root / "reports",
        help="Output directory for XLSX and baseline_2docs.md (default: reports/)",
    )
    parser.add_argument(
        "--no-aggregate",
        action="store_true",
        help="Skip running aggregate_failures on output XLSX files",
    )
    parser.add_argument(
        "--report-name",
        type=str,
        default="baseline_2docs.md",
        help="Output report filename (e.g. after_2docs.md for P5)",
    )
    parser.add_argument(
        "--prefix",
        type=str,
        default="baseline",
        help="Prefix for output XLSX filenames (e.g. after for P5)",
    )
    args = parser.parse_args()

    doc_paths = []
    if args.doc1 is not None:
        doc_paths.append(args.doc1)
    if args.doc2 is not None:
        doc_paths.append(args.doc2)
    if len(doc_paths) < 2:
        defaults = _default_doc_paths()
        if len(defaults) >= 2:
            doc_paths = defaults
            print(f"Using default paths: {doc_paths[0]}, {doc_paths[1]}")
        else:
            print(
                "Provide two DOCX paths, e.g. "
                "python scripts/run_regression_2docs.py doc1.docx doc2.docx",
                file=sys.stderr,
            )
            print(_default_doc_resolution_hint(), file=sys.stderr)
            return 1

    out = run_regression(
        doc_paths,
        args.output_dir,
        run_aggregate=not args.no_aggregate,
        report_name=args.report_name,
        output_prefix=args.prefix,
    )
    print(f"Report written to {out['report_path']}")
    if out.get("aggregate_path"):
        print(f"Aggregate prefix: {out['aggregate_path']}.csv / .json")
    return 0


if __name__ == "__main__":
    sys.exit(main())
