"""
Telemetry collection for performance monitoring and diagnostics.

SCRUM-6: Extended to include tool version, git commit, and run timestamp.
Phase 6: run_id, extractor_engine, quality_score, quality_flags,
failure_reason_code, totals_candidates_found, totals_equations_solved.
"""

import subprocess
import time
import uuid
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, cast


@dataclass
class TableTelemetry:
    """Telemetry data for a single table validation.

    Phase 6: Extraction and totals metadata for traceability.
    """

    table_index: int
    heading: str | None
    validator_type: str | None
    runtime_ms: float
    row_count: int
    cell_count: int
    status_enum: str
    rule_id: str | None = None
    exception_type: str | None = None
    # Phase 6: extraction and totals traceability
    extractor_engine: str | None = None
    quality_score: float | None = None
    quality_flags: List[str] | None = None
    failure_reason_code: str | None = None
    totals_candidates_found: int | None = None
    totals_equations_solved: int | None = None
    # R1: per-table baseline telemetry
    engine_attempts: List[str] | None = None
    invariants_failed: List[str] | None = None
    grid_cols_expected: int | None = None
    grid_cols_built: int | None = None
    grid_span_count: int | None = None
    vmerge_count: int | None = None
    # P3: heading-table association for XLSX export
    heading_source: str | None = None
    heading_confidence: float | None = None
    heading_candidates: List[Dict[str, Any]] | None = None
    heading_chosen_reason: str | None = None
    # Phase 0: classifier and extractor metadata for observability
    classifier_primary_type: str | None = None
    classifier_confidence: float | None = None
    classifier_reason: str | None = None
    extractor_usable_reason: str | None = None
    assertions_count: int | None = None
    # Phase 9: Render-first extraction telemetry
    conversion_mode: str | None = None  # local_soffice
    structure_recognizer: str | None = None  # baseline_grid / table_transformer
    ocr_engine: str | None = None  # tesseract / easyocr
    token_coverage_ratio: float | None = None
    mean_cell_confidence: float | None = None
    p10_cell_confidence: float | None = None
    empty_cell_ratio: float | None = None
    debug_artifact_path: str | None = None


@dataclass
class RunTelemetry:
    """Complete telemetry for an audit run.

    SCRUM-6: Extended with tool_version, git_commit_hash, and run_timestamp.
    Phase 6: run_id for traceability.
    """

    total_runtime_ms: float
    table_count: int
    tables: list[TableTelemetry] = field(default_factory=list)
    start_time: float = field(default_factory=time.time)
    end_time: float | None = None
    # SCRUM-6: Build identification
    tool_version: str = "unknown"
    git_commit_hash: str = "unknown"
    run_timestamp: str = field(
        default_factory=lambda: datetime.now(timezone.utc).isoformat()
    )
    # Phase 6: run-level traceability
    run_id: str = ""

    def to_dict(self) -> dict[str, Any]:
        """Convert to dictionary for serialization.

        SCRUM-6: Includes build identification fields.
        Phase 6: Includes run_id and per-table extraction/totals fields.
        """
        return {
            "total_runtime_ms": self.total_runtime_ms,
            "table_count": self.table_count,
            "start_time": self.start_time,
            "end_time": self.end_time,
            "tool_version": self.tool_version,
            "git_commit_hash": self.git_commit_hash,
            "run_timestamp": self.run_timestamp,
            "run_id": self.run_id,
            "tables": [
                {
                    "table_index": t.table_index,
                    "heading": t.heading,
                    "validator_type": t.validator_type,
                    "runtime_ms": t.runtime_ms,
                    "row_count": t.row_count,
                    "cell_count": t.cell_count,
                    "status_enum": t.status_enum,
                    "rule_id": t.rule_id,
                    "exception_type": t.exception_type,
                    "extractor_engine": t.extractor_engine,
                    "quality_score": t.quality_score,
                    "quality_flags": t.quality_flags,
                    "failure_reason_code": t.failure_reason_code,
                    "totals_candidates_found": t.totals_candidates_found,
                    "totals_equations_solved": t.totals_equations_solved,
                    "engine_attempts": t.engine_attempts,
                    "invariants_failed": t.invariants_failed,
                    "grid_cols_expected": t.grid_cols_expected,
                    "grid_cols_built": t.grid_cols_built,
                    "gridSpan_count": t.grid_span_count,
                    "vMerge_count": t.vmerge_count,
                    "heading_source": t.heading_source,
                    "heading_confidence": t.heading_confidence,
                    "heading_candidates": t.heading_candidates,
                    "heading_chosen_reason": t.heading_chosen_reason,
                    "classifier_primary_type": t.classifier_primary_type,
                    "classifier_confidence": t.classifier_confidence,
                    "classifier_reason": t.classifier_reason,
                    "extractor_usable_reason": t.extractor_usable_reason,
                    "assertions_count": t.assertions_count,
                    # Phase 9: Render-first extraction telemetry
                    "conversion_mode": t.conversion_mode,
                    "structure_recognizer": t.structure_recognizer,
                    "ocr_engine": t.ocr_engine,
                    "token_coverage_ratio": t.token_coverage_ratio,
                    "mean_cell_confidence": t.mean_cell_confidence,
                    "p10_cell_confidence": t.p10_cell_confidence,
                    "empty_cell_ratio": t.empty_cell_ratio,
                    "debug_artifact_path": t.debug_artifact_path,
                }
                for t in self.tables
            ],
        }


class TelemetryCollector:
    """Collects performance telemetry during audit runs.

    SCRUM-6: Extended with tool version and git commit detection.
    """

    # Default version - can be overridden from pyproject.toml or __version__
    DEFAULT_VERSION = "1.0.0"

    def __init__(self):
        """Initialize telemetry collector."""
        self.run_telemetry = RunTelemetry(
            total_runtime_ms=0.0,
            table_count=0,
        )
        self._current_table_start: float | None = None
        self._current_table_index: int = 0

    @staticmethod
    def _get_tool_version() -> str:
        """Get tool version from pyproject.toml or package metadata.

        SCRUM-6: Returns version string for build identification.
        """
        try:
            # Try to read from pyproject.toml
            pyproject_path = Path(__file__).parent.parent.parent / "pyproject.toml"
            if pyproject_path.exists():
                content = pyproject_path.read_text(encoding="utf-8")
                for line in content.split("\n"):
                    if line.strip().startswith("version"):
                        # Extract version from 'version = "x.y.z"'
                        parts = line.split("=", 1)
                        if len(parts) == 2:
                            version = parts[1].strip().strip('"').strip("'")
                            return version
        except Exception:
            pass

        return TelemetryCollector.DEFAULT_VERSION

    @staticmethod
    def _get_git_commit_hash() -> str:
        """Get current git commit hash if in a git repository.

        SCRUM-6: Returns short commit hash for build identification.
        """
        try:
            result = subprocess.run(
                ["git", "rev-parse", "--short", "HEAD"],
                capture_output=True,
                text=True,
                cwd=Path(__file__).parent,
                timeout=5,
            )
            if result.returncode == 0:
                return result.stdout.strip()
        except Exception:
            pass

        return "unknown"

    def start_run(self) -> None:
        """Start tracking a new audit run.

        SCRUM-6: Automatically populates version and commit info.
        Phase 6: Generates run_id for traceability.
        """
        self.run_telemetry = RunTelemetry(
            total_runtime_ms=0.0,
            table_count=0,
            tool_version=self._get_tool_version(),
            git_commit_hash=self._get_git_commit_hash(),
            run_timestamp=datetime.now(timezone.utc).isoformat(),
            run_id=uuid.uuid4().hex,
        )
        self._current_table_index = 0

    def start_table(self, heading: str | None = None) -> None:
        """Start tracking a table validation."""
        self._current_table_start = time.time()
        self._current_table_index = len(self.run_telemetry.tables)

    def end_table(
        self,
        df,
        heading: str | None = None,
        validator_type: str | None = None,
        result: dict[str, Any] | None = None,
    ) -> None:
        """
        End tracking a table validation and record metrics.

        Args:
            df: DataFrame that was validated (for row/cell counts)
            heading: Table heading
            validator_type: Type of validator used
            result: Validation result dictionary (for status_enum, rule_id, exception_type)
        """
        if self._current_table_start is None:
            return  # No table was started

        runtime_ms = (time.time() - self._current_table_start) * 1000

        # Calculate row and cell counts
        row_count = len(df) if df is not None and not df.empty else 0
        cell_count = (
            row_count * len(df.columns) if df is not None and not df.empty else 0
        )

        # Extract status and Phase 6 extraction/totals from result
        status_enum = "UNKNOWN"
        rule_id = None
        exception_type = None
        extractor_engine = None
        quality_score = None
        quality_flags = None
        failure_reason_code = None
        totals_candidates_found = None
        totals_equations_solved = None
        engine_attempts = None
        invariants_failed = None
        grid_cols_expected = None
        grid_cols_built = None
        grid_span_count = None
        vmerge_count = None

        if result:
            status_enum = result.get("status_enum", "UNKNOWN")
            rule_id = result.get("rule_id")
            exception_type = result.get("exception_type")
            ctx = result.get("context") or {}
            extractor_engine = ctx.get("extractor_engine")
            quality_score = ctx.get("quality_score")
            quality_flags = ctx.get("quality_flags")
            failure_reason_code = ctx.get("failure_reason_code")
            total_row_meta = ctx.get("total_row_metadata") or {}
            totals_candidates_found = total_row_meta.get("totals_candidates_found")
            totals_equations_solved = total_row_meta.get("totals_equations_solved")
            engine_attempts = ctx.get("engine_attempts")
            invariants_failed = ctx.get("invariants_failed")
            grid_cols_expected = ctx.get("grid_cols_expected")
            grid_cols_built = ctx.get("grid_cols_built")
            grid_span_count = ctx.get("gridSpan_count")
            vmerge_count = ctx.get("vMerge_count")
            heading_source = ctx.get("heading_source")
            heading_confidence = ctx.get("heading_confidence")
            heading_candidates = ctx.get("heading_candidates")
            heading_chosen_reason = ctx.get("heading_chosen_reason")
            classifier_primary_type = ctx.get("classifier_primary_type")
            classifier_confidence = ctx.get("classifier_confidence")
            classifier_reason = ctx.get("classifier_reason")
            extractor_usable_reason = ctx.get("extractor_usable_reason")
            assertions_count = result.get("assertions_count")
            if assertions_count is None:
                assertions_count = ctx.get("assertions_count")
            # Phase 9: Render-first extraction telemetry
            conversion_mode = ctx.get("conversion_mode")
            structure_recognizer = ctx.get("structure_recognizer")
            ocr_engine = ctx.get("ocr_engine")
            token_coverage_ratio = ctx.get("token_coverage_ratio")
            mean_cell_confidence = ctx.get("mean_cell_confidence")
            p10_cell_confidence = ctx.get("p10_cell_confidence")
            empty_cell_ratio = ctx.get("empty_cell_ratio")
            debug_artifact_path = ctx.get("debug_artifact_path")
        else:
            heading_source = None
            heading_confidence = None
            heading_candidates = None
            heading_chosen_reason = None
            classifier_primary_type = None
            classifier_confidence = None
            classifier_reason = None
            extractor_usable_reason = None
            assertions_count = None
            # Phase 9: defaults for non-render-first
            conversion_mode = None
            structure_recognizer = None
            ocr_engine = None
            token_coverage_ratio = None
            mean_cell_confidence = None
            p10_cell_confidence = None
            empty_cell_ratio = None
            debug_artifact_path = None

        table_telemetry = TableTelemetry(
            table_index=self._current_table_index,
            heading=heading,
            validator_type=validator_type,
            runtime_ms=runtime_ms,
            row_count=row_count,
            cell_count=cell_count,
            status_enum=status_enum,
            rule_id=rule_id,
            exception_type=exception_type,
            extractor_engine=extractor_engine,
            quality_score=quality_score,
            quality_flags=quality_flags,
            failure_reason_code=failure_reason_code,
            totals_candidates_found=totals_candidates_found,
            totals_equations_solved=totals_equations_solved,
            engine_attempts=engine_attempts,
            invariants_failed=invariants_failed,
            grid_cols_expected=grid_cols_expected,
            grid_cols_built=grid_cols_built,
            grid_span_count=grid_span_count,
            vmerge_count=vmerge_count,
            heading_source=heading_source,
            heading_confidence=heading_confidence,
            heading_candidates=heading_candidates,
            heading_chosen_reason=heading_chosen_reason,
            classifier_primary_type=classifier_primary_type,
            classifier_confidence=classifier_confidence,
            classifier_reason=classifier_reason,
            extractor_usable_reason=extractor_usable_reason,
            assertions_count=assertions_count,
            # Phase 9: Render-first extraction telemetry
            conversion_mode=conversion_mode,
            structure_recognizer=structure_recognizer,
            ocr_engine=ocr_engine,
            token_coverage_ratio=token_coverage_ratio,
            mean_cell_confidence=mean_cell_confidence,
            p10_cell_confidence=p10_cell_confidence,
            empty_cell_ratio=empty_cell_ratio,
            debug_artifact_path=debug_artifact_path,
        )

        self.run_telemetry.tables.append(table_telemetry)
        self.run_telemetry.table_count = len(self.run_telemetry.tables)
        self._current_table_start = None

    def end_run(self) -> None:
        """End tracking the audit run and calculate total runtime."""
        self.run_telemetry.end_time = time.time()
        self.run_telemetry.total_runtime_ms = (
            self.run_telemetry.end_time - self.run_telemetry.start_time
        ) * 1000

    def get_telemetry(self) -> RunTelemetry:
        """Get current telemetry data."""
        return cast(RunTelemetry, self.run_telemetry)

    def get_summary(self) -> dict[str, Any]:
        """
        Get a summary of telemetry data.

        Returns:
            Dict with summary statistics
        """
        if not self.run_telemetry.tables:
            return {
                "total_runtime_ms": self.run_telemetry.total_runtime_ms,
                "table_count": 0,
                "avg_table_runtime_ms": 0.0,
                "total_rows_processed": 0,
                "total_cells_processed": 0,
            }

        total_table_runtime = sum(t.runtime_ms for t in self.run_telemetry.tables)
        total_rows = sum(t.row_count for t in self.run_telemetry.tables)
        total_cells = sum(t.cell_count for t in self.run_telemetry.tables)

        return {
            "total_runtime_ms": self.run_telemetry.total_runtime_ms,
            "table_count": self.run_telemetry.table_count,
            "avg_table_runtime_ms": total_table_runtime
            / self.run_telemetry.table_count,
            "total_rows_processed": total_rows,
            "total_cells_processed": total_cells,
            "tables_by_status": self._count_by_status(),
            "tables_by_validator": self._count_by_validator(),
        }

    def _count_by_status(self) -> dict[str, int]:
        """Count tables by status enum."""
        counts: Dict[str, int] = {}
        for table in self.run_telemetry.tables:
            status = str(table.status_enum or "").strip().upper() or "UNKNOWN"
            counts[status] = counts.get(status, 0) + 1
        return counts

    def _count_by_validator(self) -> dict[str, int]:
        """Count tables by validator type."""
        counts: Dict[str, int] = {}
        for table in self.run_telemetry.tables:
            validator = table.validator_type or "UNKNOWN"
            counts[validator] = counts.get(validator, 0) + 1
        return counts
