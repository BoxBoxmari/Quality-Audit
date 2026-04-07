from __future__ import annotations

import asyncio
import json
import multiprocessing
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Callable, Dict, List, Literal, Optional, Sequence, Tuple

from quality_audit.cli import main as cli_main
from quality_audit.config.tax_rate import TaxRateConfig
from quality_audit.core.cache_manager import AuditContext, LRUCacheManager
from quality_audit.io import ExcelWriter, FileHandler
from quality_audit.io.word_reader import AsyncWordReader
from quality_audit.services.audit_service import AuditService
from quality_audit.services.batch_processor import BatchProcessor

InputSourceType = Literal["folder", "file", "multi_files"]
TaxMode = Literal["all", "individual"]
LogFn = Callable[[str], None]
ProgressFn = Callable[[Dict[str, Any]], None]


@dataclass(frozen=True)
class RunSpec:
    input_source_type: InputSourceType
    input_source_path: Optional[Path]
    selected_files: Tuple[Path, ...]
    discovered_files: Tuple[Path, ...]
    base_path: Optional[Path]
    output_dir: Path
    tax_mode: TaxMode
    all_rate_percent: Optional[float]
    default_rate_percent: Optional[float]
    per_file_rates_percent: Dict[str, float]
    cache_size: int = 1000
    log_level: str = "INFO"
    previous_output: Optional[Path] = None


def discover_docx(
    input_source_type: InputSourceType,
    input_source_path: Optional[Path],
    selected_files: Sequence[Path] | None = None,
) -> Tuple[List[Path], Optional[Path]]:
    discovered: List[Path] = []
    base_path: Optional[Path] = None
    if input_source_type == "folder" and input_source_path is not None:
        folder = input_source_path.resolve()
        if folder.is_dir():
            discovered = sorted(
                [
                    p.resolve()
                    for p in folder.rglob("*.docx")
                    if p.is_file() and not p.name.startswith("~$")
                ]
            )
            base_path = folder
    elif input_source_type == "file" and input_source_path is not None:
        file_path = input_source_path.resolve()
        if file_path.is_file() and file_path.suffix.lower() == ".docx":
            discovered = [file_path]
            base_path = file_path.parent
    elif input_source_type == "multi_files":
        picked = selected_files or []
        discovered = sorted(
            [
                p.resolve()
                for p in picked
                if p.is_file()
                and p.suffix.lower() == ".docx"
                and not p.name.startswith("~$")
            ]
        )
        if discovered:
            parents = {p.parent.resolve() for p in discovered}
            base_path = parents.pop() if len(parents) == 1 else None
    return discovered, base_path


def file_key_for(path: Path, base_path: Optional[Path]) -> str:
    if base_path is not None:
        try:
            return path.resolve().relative_to(base_path.resolve()).as_posix()
        except ValueError:
            pass
    return path.name


def build_tax_config(spec: RunSpec) -> TaxRateConfig:
    if spec.tax_mode == "all":
        if spec.all_rate_percent is None:
            raise ValueError("all mode requires all_rate_percent")
        return TaxRateConfig(mode="all", all_rate=float(spec.all_rate_percent) / 100.0)

    if spec.tax_mode == "individual":
        map_data: Dict[str, float] = {}
        default_pct = (
            float(spec.default_rate_percent)
            if spec.default_rate_percent is not None
            else float(
                spec.all_rate_percent if spec.all_rate_percent is not None else 25.0
            )
        )
        map_data["default"] = default_pct / 100.0
        for file_path in spec.discovered_files:
            key = file_key_for(file_path, spec.base_path)
            pct = spec.per_file_rates_percent.get(key, default_pct)
            map_data[key] = float(pct) / 100.0
        return TaxRateConfig(
            mode="individual",
            map_data=map_data,
            default_rate=map_data["default"],
        )

    raise ValueError(f"Unsupported tax mode: {spec.tax_mode}")


def build_cli_argv(spec: RunSpec, tax_map_path: Optional[Path] = None) -> List[str]:
    if spec.input_source_type == "multi_files":
        raise ValueError("multi_files is not represented by single CLI input_path")
    if spec.input_source_path is None:
        raise ValueError("input_source_path is required for CLI argv")

    argv = [str(spec.input_source_path)]
    argv.extend(["--output-dir", str(spec.output_dir)])
    argv.extend(["--cache-size", str(spec.cache_size)])
    if spec.log_level and spec.log_level != "INFO":
        argv.extend(["--log-level", spec.log_level])
    if spec.previous_output is not None:
        argv.extend(["--previous-output", str(spec.previous_output)])

    argv.extend(["--tax-rate-mode", spec.tax_mode])
    if spec.tax_mode == "all":
        if spec.all_rate_percent is None:
            raise ValueError("all mode requires all_rate_percent")
        argv.extend(["--tax-rate", str(spec.all_rate_percent)])
    elif spec.tax_mode == "individual":
        if tax_map_path is None:
            raise ValueError("individual mode requires tax_map_path")
        argv.extend(["--tax-rate-map", str(tax_map_path)])

    return argv


def write_tax_map_for_cli(spec: RunSpec, target_path: Path) -> Path:
    if spec.tax_mode != "individual":
        raise ValueError("tax map is only applicable for individual mode")
    default_pct = (
        float(spec.default_rate_percent)
        if spec.default_rate_percent is not None
        else float(spec.all_rate_percent if spec.all_rate_percent is not None else 25.0)
    )
    files_payload: dict[str, float] = {}
    payload = {"default": default_pct, "files": files_payload}
    for file_path in spec.discovered_files:
        key = file_key_for(file_path, spec.base_path)
        files_payload[key] = float(spec.per_file_rates_percent.get(key, default_pct))
    target_path.parent.mkdir(parents=True, exist_ok=True)
    with open(target_path, "w", encoding="utf-8") as f:
        json.dump(payload, f, indent=2, ensure_ascii=False)
    return target_path


def _optimal_concurrency() -> int:
    try:
        return max(min(multiprocessing.cpu_count() * 2, 8), 2)
    except Exception:
        return 2


def run_spec(spec: RunSpec, log: LogFn, progress: Optional[ProgressFn] = None) -> int:
    spec.output_dir.mkdir(parents=True, exist_ok=True)
    if spec.input_source_type in ("folder", "file"):
        tax_map_path = None
        if spec.tax_mode == "individual":
            tax_map_path = write_tax_map_for_cli(
                spec, spec.output_dir / "tax_rate_map.json"
            )
        argv = build_cli_argv(spec, tax_map_path=tax_map_path)
        log("CLI contract: " + " ".join(argv))
        return int(cli_main(argv))

    # multi_files path keeps CLI batch contract semantics without direct UI loops
    tax_config = build_tax_config(spec)
    context = AuditContext(
        cache=LRUCacheManager(max_size=spec.cache_size),
        tax_rate_config=tax_config,
        base_path=spec.base_path
        or (
            spec.discovered_files[0].parent
            if spec.discovered_files
            else spec.output_dir
        ),
    )
    max_workers = _optimal_concurrency()
    async_reader = AsyncWordReader(max_workers=max_workers)
    service = AuditService(
        context=context,
        async_word_reader=async_reader,
        excel_writer=ExcelWriter(
            previous_output_path=(
                str(spec.previous_output) if spec.previous_output else None
            )
        ),
        file_handler=FileHandler(),
    )
    batch = BatchProcessor(service, max_concurrent=max_workers)
    total_files = len(spec.discovered_files)
    log(f"Batch contract: {total_files} file(s), workers={max_workers}")

    processed_count = 0

    def _on_file_complete(item: Dict[str, Any]) -> None:
        nonlocal processed_count
        processed_count += 1
        file_name = Path(item.get("input_file", "")).name
        if progress is not None:
            progress(
                {
                    "processed": processed_count,
                    "total": total_files,
                    "current_file": file_name,
                    "success": bool(item.get("success", False)),
                    "error": item.get("error"),
                    "error_code": item.get("error_code") or item.get("error_type"),
                    "stage": item.get("stage") or "batch_process",
                    "source_file": item.get("input_file"),
                    "run_id": item.get("run_id"),
                }
            )

    results = asyncio.run(
        batch.process_batch_async(
            [str(p) for p in spec.discovered_files],
            str(spec.output_dir),
            on_file_complete=_on_file_complete,
        )
    )
    failed = [r for r in results if not r.get("success", False)]
    for r in results:
        name = Path(r.get("input_file", "")).name
        if r.get("success", False):
            log(f"SUCCESS {name}")
        else:
            log(f"FAILED {name}: {r.get('error', 'Unknown error')}")
    return 0 if not failed else 1
