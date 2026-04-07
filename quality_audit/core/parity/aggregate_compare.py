"""
Compare aggregate_failures.json documents for baseline parity.

Modes:
- strict: same aggregate_schema_version (optional), identical set of group keys,
  and for each key the same count and same sources (order-independent).
- baseline_keys: every group present in the baseline must match in the current
  document (count + sources). Extra groups in the current document are allowed
  unless allow_extra_groups_in_current is False (then equivalent to strict on keys).

Normalization: string fields are stripped; None becomes "". Sources may be a list
of strings or a single string with ";" separators (CSV round-trip).
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from enum import Enum
from pathlib import Path
from typing import Any, Iterable, Mapping, cast

GROUP_FIELD_NAMES = (
    "validator_type",
    "failure_reason_code",
    "rule_id",
    "extractor_engine",
    "total_row_method",
)

GroupKey = tuple[str, str, str, str, str]


class AggregateCompareMode(str, Enum):
    STRICT = "strict"
    BASELINE_KEYS = "baseline_keys"


def _s(v: Any) -> str:
    if v is None:
        return ""
    return str(v).strip()


def coerce_sources(value: Any) -> tuple[str, ...]:
    """Normalize sources to a sorted tuple of non-empty strings."""
    if value is None:
        return ()
    if isinstance(value, str):
        parts = [p.strip() for p in value.split(";") if p.strip()]
        return tuple(sorted(parts))
    if isinstance(value, Iterable) and not isinstance(value, (bytes, dict)):
        parts = [_s(x) for x in value if _s(x)]
        return tuple(sorted(parts))
    return ()


def group_key_from_record(rec: Mapping[str, Any]) -> GroupKey:
    # GROUP_FIELD_NAMES is a fixed 5-tuple; cast keeps mypy aware of tuple arity.
    return cast(GroupKey, tuple(_s(rec.get(name)) for name in GROUP_FIELD_NAMES))


def index_aggregate_groups(
    doc: Mapping[str, Any],
) -> dict[GroupKey, tuple[int, tuple[str, ...]]]:
    """
    Map group key -> (count, normalized sources).

    Expects doc['groups'] to be a list of records with group fields + count + sources.
    """
    groups = doc.get("groups")
    if not isinstance(groups, list):
        return {}

    out: dict[GroupKey, tuple[int, tuple[str, ...]]] = {}
    for item in groups:
        if not isinstance(item, Mapping):
            continue
        key = group_key_from_record(item)
        try:
            count = int(item.get("count", 0))
        except (TypeError, ValueError):
            count = 0
        sources = coerce_sources(item.get("sources"))
        out[key] = (count, sources)
    return out


def load_aggregate_json(path: str | Path) -> dict[str, Any]:
    p = Path(path)
    if not p.is_file():
        raise FileNotFoundError(f"Aggregate JSON not found: {p}")
    with open(p, encoding="utf-8") as f:
        data = json.load(f)
    if not isinstance(data, dict):
        raise ValueError(f"Expected JSON object at root: {p}")
    return data


@dataclass
class AggregateCompareResult:
    ok: bool
    mode: AggregateCompareMode
    schema_match: bool
    missing_in_current: list[GroupKey] = field(default_factory=list)
    missing_in_baseline: list[GroupKey] = field(default_factory=list)
    count_mismatch: list[dict[str, Any]] = field(default_factory=list)
    sources_mismatch: list[dict[str, Any]] = field(default_factory=list)
    messages: list[str] = field(default_factory=list)

    def raise_if_failed(self) -> None:
        if not self.ok:
            detail = (
                "\n".join(self.messages)
                if self.messages
                else "aggregate compare failed"
            )
            raise AssertionError(detail)


def compare_aggregate_documents(
    baseline: Mapping[str, Any],
    current: Mapping[str, Any],
    *,
    mode: AggregateCompareMode | str = AggregateCompareMode.STRICT,
    require_schema_match: bool = True,
    allow_extra_groups_in_current: bool | None = None,
) -> AggregateCompareResult:
    """
    Compare two aggregate documents produced by aggregate_failures / build_aggregate_document.

    allow_extra_groups_in_current:
    - None: default True for baseline_keys, False for strict.
    - If False, any group key only in current is reported as failure (strict key set).
    """
    if isinstance(mode, str):
        mode = AggregateCompareMode(mode)

    if allow_extra_groups_in_current is None:
        allow_extra_groups_in_current = mode is AggregateCompareMode.BASELINE_KEYS

    b_ver = _s(baseline.get("aggregate_schema_version"))
    c_ver = _s(current.get("aggregate_schema_version"))
    schema_match = b_ver == c_ver
    messages: list[str] = []

    if require_schema_match and not schema_match:
        messages.append(
            f"aggregate_schema_version mismatch: baseline={b_ver!r} current={c_ver!r}"
        )

    b_idx = index_aggregate_groups(baseline)
    c_idx = index_aggregate_groups(current)

    b_keys = set(b_idx)
    c_keys = set(c_idx)

    missing_in_current = sorted(b_keys - c_keys)
    missing_in_baseline = sorted(c_keys - b_keys)

    count_mismatch: list[dict[str, Any]] = []
    sources_mismatch: list[dict[str, Any]] = []

    keys_to_compare = b_keys
    if mode is AggregateCompareMode.STRICT:
        for k in missing_in_current:
            messages.append(f"Group missing in current: {k}")
        for k in missing_in_baseline:
            messages.append(f"Extra group in current (not in baseline): {k}")
        keys_to_compare = b_keys | c_keys
    else:
        for k in missing_in_current:
            messages.append(f"Baseline group missing in current: {k}")
        if not allow_extra_groups_in_current:
            for k in missing_in_baseline:
                messages.append(f"Extra group in current (not in baseline): {k}")

    for k in sorted(keys_to_compare):
        if k not in b_idx or k not in c_idx:
            continue
        bc, bs = b_idx[k]
        cc, cs = c_idx[k]
        if bc != cc:
            count_mismatch.append(
                {"key": list(k), "baseline_count": bc, "current_count": cc}
            )
            messages.append(f"Count mismatch for {k}: baseline={bc} current={cc}")
        if bs != cs:
            sources_mismatch.append(
                {
                    "key": list(k),
                    "baseline_sources": list(bs),
                    "current_sources": list(cs),
                }
            )
            messages.append(f"Sources mismatch for {k}: baseline={bs!r} current={cs!r}")

    ok = not messages
    return AggregateCompareResult(
        ok=ok,
        mode=mode,
        schema_match=schema_match,
        missing_in_current=missing_in_current,
        missing_in_baseline=missing_in_baseline,
        count_mismatch=count_mismatch,
        sources_mismatch=sources_mismatch,
        messages=messages,
    )


def compare_aggregate_paths(
    baseline_path: str | Path,
    current_path: str | Path,
    **kwargs: Any,
) -> AggregateCompareResult:
    """Load JSON from paths and compare."""
    return compare_aggregate_documents(
        load_aggregate_json(baseline_path),
        load_aggregate_json(current_path),
        **kwargs,
    )
