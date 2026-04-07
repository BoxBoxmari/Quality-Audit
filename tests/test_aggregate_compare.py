"""Unit tests for quality_audit.core.parity.aggregate_compare."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from quality_audit.core.parity.aggregate_compare import (
    AggregateCompareMode,
    AggregateCompareResult,
    coerce_sources,
    compare_aggregate_documents,
    compare_aggregate_paths,
    group_key_from_record,
    index_aggregate_groups,
    load_aggregate_json,
)


def _group(
    *,
    validator_type: str = "generic",
    failure_reason_code: str = "X",
    rule_id: str = "R1",
    extractor_engine: str = "word",
    total_row_method: str = "sum",
    count: int = 1,
    sources: list[str] | str | None = None,
) -> dict:
    if sources is None:
        sources = ["a.docx"]
    return {
        "validator_type": validator_type,
        "failure_reason_code": failure_reason_code,
        "rule_id": rule_id,
        "extractor_engine": extractor_engine,
        "total_row_method": total_row_method,
        "count": count,
        "sources": sources,
    }


def _doc(version: str = "1", groups: list | None = None) -> dict:
    return {
        "aggregate_schema_version": version,
        "groups": groups or [],
    }


def test_coerce_sources_none_and_empty() -> None:
    assert coerce_sources(None) == ()
    assert coerce_sources("") == ()
    assert coerce_sources([]) == ()


def test_coerce_sources_string_semicolon_sorted() -> None:
    assert coerce_sources("b; a; c") == ("a", "b", "c")
    assert coerce_sources("  x  ; y ") == ("x", "y")


def test_coerce_sources_list_sorted_and_strips() -> None:
    assert coerce_sources(["b", " a "]) == ("a", "b")
    assert coerce_sources(["", "z", None]) == ("z",)


def test_coerce_sources_non_iterable_returns_empty() -> None:
    assert coerce_sources({}) == ()
    assert coerce_sources(123) == ()


def test_group_key_from_record_strips_and_none() -> None:
    key = group_key_from_record(
        {
            "validator_type": "  t  ",
            "failure_reason_code": None,
            "rule_id": "r",
            "extractor_engine": "e",
            "total_row_method": "m",
        }
    )
    assert key == ("t", "", "r", "e", "m")


def test_index_aggregate_groups_skips_non_mappings_and_bad_count() -> None:
    doc = _doc(
        groups=[
            _group(count=2),
            "not-a-dict",
            {**_group(count="nope"), "count": "bad"},
        ]
    )
    idx = index_aggregate_groups(doc)
    k = ("generic", "X", "R1", "word", "sum")
    assert idx[k][0] == 0  # last record overwrites with invalid count -> 0


def test_index_aggregate_groups_last_record_wins_same_key() -> None:
    doc = _doc(
        groups=[
            _group(count=1, sources=["a"]),
            _group(count=5, sources=["b"]),
        ]
    )
    k = ("generic", "X", "R1", "word", "sum")
    assert index_aggregate_groups(doc)[k] == (5, ("b",))


def test_index_aggregate_groups_missing_or_wrong_groups() -> None:
    assert index_aggregate_groups({}) == {}
    assert index_aggregate_groups({"groups": None}) == {}
    assert index_aggregate_groups({"groups": {}}) == {}


def test_compare_strict_identical_ok() -> None:
    g = [_group()]
    b = _doc(groups=g)
    c = _doc(groups=[dict(g[0])])
    r = compare_aggregate_documents(b, c, mode=AggregateCompareMode.STRICT)
    assert r.ok
    assert r.schema_match
    assert not r.messages


def test_compare_strict_sources_order_independent() -> None:
    b = _doc(groups=[_group(sources=["a", "b"])])
    c = _doc(groups=[_group(sources=["b", "a"])])
    r = compare_aggregate_documents(b, c)
    assert r.ok


def test_compare_strict_string_vs_list_sources_equivalent() -> None:
    b = _doc(groups=[_group(sources="b; a")])
    c = _doc(groups=[_group(sources=["a", "b"])])
    r = compare_aggregate_documents(b, c)
    assert r.ok


def test_compare_strict_missing_group_in_current() -> None:
    b = _doc(groups=[_group(), _group(rule_id="R2")])
    c = _doc(groups=[_group()])
    r = compare_aggregate_documents(b, c, mode="strict")
    assert not r.ok
    assert any("Group missing in current" in m for m in r.messages)
    assert r.missing_in_current


def test_compare_strict_extra_group_in_current() -> None:
    b = _doc(groups=[_group()])
    c = _doc(groups=[_group(), _group(rule_id="R2")])
    r = compare_aggregate_documents(b, c)
    assert not r.ok
    assert any("Extra group in current" in m for m in r.messages)
    assert r.missing_in_baseline


def test_compare_count_mismatch() -> None:
    b = _doc(groups=[_group(count=3)])
    c = _doc(groups=[_group(count=4)])
    r = compare_aggregate_documents(b, c)
    assert not r.ok
    assert r.count_mismatch
    assert any("Count mismatch" in m for m in r.messages)


def test_compare_sources_mismatch() -> None:
    b = _doc(groups=[_group(sources=["a"])])
    c = _doc(groups=[_group(sources=["b"])])
    r = compare_aggregate_documents(b, c)
    assert not r.ok
    assert r.sources_mismatch


def test_compare_schema_mismatch_default_required() -> None:
    b = _doc(version="1", groups=[_group()])
    c = _doc(version="2", groups=[_group()])
    r = compare_aggregate_documents(b, c)
    assert not r.ok
    assert not r.schema_match
    assert any("aggregate_schema_version mismatch" in m for m in r.messages)


def test_compare_schema_mismatch_ignored_when_not_required() -> None:
    b = _doc(version="1", groups=[_group()])
    c = _doc(version="2", groups=[_group()])
    r = compare_aggregate_documents(b, c, require_schema_match=False)
    assert r.ok
    assert not r.schema_match


def test_compare_baseline_keys_allows_extra_in_current() -> None:
    b = _doc(groups=[_group()])
    c = _doc(groups=[_group(), _group(rule_id="EXTRA")])
    r = compare_aggregate_documents(b, c, mode=AggregateCompareMode.BASELINE_KEYS)
    assert r.ok
    assert r.missing_in_baseline  # still tracked


def test_compare_baseline_keys_missing_baseline_group_fails() -> None:
    b = _doc(groups=[_group(), _group(rule_id="R2")])
    c = _doc(groups=[_group()])
    r = compare_aggregate_documents(b, c, mode=AggregateCompareMode.BASELINE_KEYS)
    assert not r.ok
    assert any("Baseline group missing in current" in m for m in r.messages)


def test_compare_baseline_keys_disallow_extra_behaves_like_strict_keys() -> None:
    b = _doc(groups=[_group()])
    c = _doc(groups=[_group(), _group(rule_id="EXTRA")])
    r = compare_aggregate_documents(
        b,
        c,
        mode=AggregateCompareMode.BASELINE_KEYS,
        allow_extra_groups_in_current=False,
    )
    assert not r.ok
    assert any("Extra group in current" in m for m in r.messages)


def test_load_aggregate_json_missing_raises(tmp_path: Path) -> None:
    p = tmp_path / "missing.json"
    with pytest.raises(FileNotFoundError, match="Aggregate JSON not found"):
        load_aggregate_json(p)


def test_load_aggregate_json_non_object_root_raises(tmp_path: Path) -> None:
    p = tmp_path / "bad.json"
    p.write_text("[1,2]", encoding="utf-8")
    with pytest.raises(ValueError, match="Expected JSON object"):
        load_aggregate_json(p)


def test_load_aggregate_json_and_compare_paths(tmp_path: Path) -> None:
    b = tmp_path / "b.json"
    c = tmp_path / "c.json"
    payload = _doc(groups=[_group()])
    b.write_text(json.dumps(payload), encoding="utf-8")
    c.write_text(json.dumps(payload), encoding="utf-8")
    r = compare_aggregate_paths(b, c)
    assert r.ok


def test_aggregate_compare_result_raise_if_failed() -> None:
    ok = AggregateCompareResult(
        ok=True,
        mode=AggregateCompareMode.STRICT,
        schema_match=True,
    )
    ok.raise_if_failed()

    bad = AggregateCompareResult(
        ok=False,
        mode=AggregateCompareMode.STRICT,
        schema_match=True,
        messages=["a", "b"],
    )
    with pytest.raises(AssertionError, match="a\nb"):
        bad.raise_if_failed()

    empty_msgs = AggregateCompareResult(
        ok=False,
        mode=AggregateCompareMode.STRICT,
        schema_match=True,
        messages=[],
    )
    with pytest.raises(AssertionError, match="aggregate compare failed"):
        empty_msgs.raise_if_failed()
