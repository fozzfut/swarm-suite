"""Tests for the enterprise-grade hardening pass.

Covers:
  * Input length / count / payload limits raise ValueError -> MCP boundary
    converts to INVALID_PARAMS, so a bad caller can't fill disk or memory.
  * BoundedRecordCache LRU eviction in JudgingEngine, VerificationStore,
    PgveStore, FlowStore -- in-memory cache stays bounded; older records
    persist on disk and reload on demand.
  * DSL parser rejects extreme input (huge source, deep nesting, too many
    nodes) with FlowSyntaxError instead of stack-overflowing.
  * schema_version > current logs a warning on every from_dict for
    judging / verification / pgve / flow.
"""

from __future__ import annotations

import json
import logging

import pytest

from swarm_core.models.completion import CompletionRecord, SubtaskRecord

from swarm_kb._limits import (
    DEFAULT_MAX_RECORDS,
    MAX_BLOCKING_ISSUES,
    MAX_CANDIDATES_HARD,
    MAX_DIMENSIONS,
    MAX_EVIDENCE_PER_REPORT,
    MAX_FOLLOW_UPS,
    MAX_PAYLOAD_BYTES,
    MAX_SUGGESTED_CHANGES,
    MAX_TEXT_LEN,
    BoundedRecordCache,
    check_count,
    check_payload_size,
    check_text,
)
from swarm_kb.dsl import (
    MAX_NODES,
    MAX_PARSE_DEPTH,
    MAX_SOURCE_LEN,
    FlowSyntaxError,
    FlowStore,
    parse_flow,
)
from swarm_kb.judging import (
    DEFAULT_DIMENSIONS,
    Judging,
    JudgingEngine,
    Judgment,
    JudgingSynthesis,
)
from swarm_kb.pgve import Candidate, Evaluation, PgveSession, PgveStore
from swarm_kb.verification import (
    VerificationEvidence,
    VerificationReport,
    VerificationStore,
    VerificationVerdict,
)


# ============================================================================
# _limits helpers
# ============================================================================


def test_check_text_under_limit_ok():
    check_text("x" * (MAX_TEXT_LEN), "field")


def test_check_text_over_limit_raises():
    with pytest.raises(ValueError, match="exceeds limit"):
        check_text("x" * (MAX_TEXT_LEN + 1), "field")


def test_check_payload_size_under_limit_ok():
    check_payload_size({"k": "v" * 100}, "payload")


def test_check_payload_size_over_limit_raises():
    big = {"k": "v" * MAX_PAYLOAD_BYTES}
    with pytest.raises(ValueError, match="exceeds limit"):
        check_payload_size(big, "payload")


def test_check_payload_size_unserialisable_raises():
    with pytest.raises(ValueError, match="not JSON-serialisable"):
        check_payload_size({"k": object()}, "payload")


def test_check_count_under_limit_ok():
    check_count([1, 2, 3], "items", 5)


def test_check_count_over_limit_raises():
    with pytest.raises(ValueError, match="exceeds limit"):
        check_count(list(range(10)), "items", 5)


# ============================================================================
# BoundedRecordCache
# ============================================================================


def test_cache_evicts_oldest_when_full():
    cache: BoundedRecordCache[str] = BoundedRecordCache(max_records=3)
    cache.put("a", "1")
    cache.put("b", "2")
    cache.put("c", "3")
    cache.put("d", "4")
    keys = cache.keys()
    assert "a" not in keys      # oldest evicted
    assert set(keys) == {"b", "c", "d"}


def test_cache_lru_touch_on_get():
    cache: BoundedRecordCache[str] = BoundedRecordCache(max_records=3)
    cache.put("a", "1")
    cache.put("b", "2")
    cache.put("c", "3")
    # Touch 'a' so it becomes most-recent.
    assert cache.get("a") == "1"
    cache.put("d", "4")
    keys = cache.keys()
    assert "b" not in keys      # 'b' is now oldest, evicted
    assert "a" in keys


def test_cache_pop_removes():
    cache: BoundedRecordCache[str] = BoundedRecordCache(max_records=5)
    cache.put("x", "1")
    assert cache.pop("x") == "1"
    assert "x" not in cache


def test_cache_max_records_validated():
    with pytest.raises(ValueError):
        BoundedRecordCache(max_records=0)


def test_cache_default_size():
    cache: BoundedRecordCache[str] = BoundedRecordCache()
    assert cache.max_records == DEFAULT_MAX_RECORDS


# ============================================================================
# Input bounds: judging
# ============================================================================


def test_judgment_rejects_oversize_rationale():
    with pytest.raises(ValueError, match="rationale.*exceeds"):
        Judgment(judge="x", dimension="d", verdict="pass",
                 rationale="x" * (MAX_TEXT_LEN + 1))


def test_judgment_rejects_too_many_suggested_changes():
    with pytest.raises(ValueError, match="suggested_changes.*exceeds"):
        Judgment(judge="x", dimension="d", verdict="pass",
                 suggested_changes=["c"] * (MAX_SUGGESTED_CHANGES + 1))


def test_judging_rejects_too_many_dimensions():
    with pytest.raises(ValueError, match="dimensions.*exceeds"):
        Judging(subject="x", dimensions=[f"d{i}" for i in range(MAX_DIMENSIONS + 1)])


def test_judging_rejects_oversize_subject():
    with pytest.raises(ValueError, match="subject.*exceeds"):
        Judging(subject="x" * (MAX_TEXT_LEN + 1), dimensions=["a"])


def test_synthesis_rejects_oversize_summary():
    with pytest.raises(ValueError, match="summary.*exceeds"):
        JudgingSynthesis(overall="pass", summary="x" * (MAX_TEXT_LEN + 1))


# ============================================================================
# Input bounds: verification
# ============================================================================


def test_evidence_rejects_oversize_summary():
    with pytest.raises(ValueError, match="summary.*exceeds"):
        VerificationEvidence(kind="manual_note", summary="x" * (MAX_TEXT_LEN + 1))


def test_evidence_rejects_oversize_payload():
    with pytest.raises(ValueError, match="data.*exceeds"):
        VerificationEvidence(kind="manual_note", summary="ok",
                             data={"k": "v" * MAX_PAYLOAD_BYTES})


def test_verdict_rejects_too_many_blockers():
    with pytest.raises(ValueError, match="blocking_issues.*exceeds"):
        VerificationVerdict(overall="fail", summary="x",
                            blocking_issues=["b"] * (MAX_BLOCKING_ISSUES + 1))


def test_verdict_rejects_too_many_followups():
    with pytest.raises(ValueError, match="follow_ups.*exceeds"):
        VerificationVerdict(overall="pass", summary="x",
                            follow_ups=["u"] * (MAX_FOLLOW_UPS + 1))


def test_report_rejects_too_many_evidence(tmp_path):
    store = VerificationStore(tmp_path)
    r = store.start(fix_session="fix-1")
    # Fill to limit, then one more.
    for i in range(MAX_EVIDENCE_PER_REPORT):
        store.add_evidence(r.id, kind="manual_note", summary=f"e{i}")
    with pytest.raises(ValueError, match="evidence count.*exceed"):
        store.add_evidence(r.id, kind="manual_note", summary="overflow")


# ============================================================================
# Input bounds: pgve
# ============================================================================


def test_candidate_rejects_oversize_content():
    with pytest.raises(ValueError, match="content.*exceeds"):
        Candidate(content="x" * (MAX_TEXT_LEN + 1))


def test_candidate_rejects_oversize_payload():
    with pytest.raises(ValueError, match="payload.*exceeds"):
        Candidate(content="ok", payload={"k": "v" * MAX_PAYLOAD_BYTES})


def test_evaluation_rejects_oversize_feedback():
    with pytest.raises(ValueError, match="feedback.*exceeds"):
        Evaluation(verdict="revise", feedback="x" * (MAX_TEXT_LEN + 1))


def test_pgve_session_rejects_oversize_task_spec():
    with pytest.raises(ValueError, match="task_spec.*exceeds"):
        PgveSession(task_spec="x" * (MAX_TEXT_LEN + 1))


def test_pgve_session_rejects_excessive_max_candidates():
    with pytest.raises(ValueError, match="exceeds hard cap"):
        PgveSession(task_spec="x", max_candidates=MAX_CANDIDATES_HARD + 1)


# ============================================================================
# Input bounds: completion (swarm-core side)
# ============================================================================


def test_subtask_record_rejects_oversize_summary():
    with pytest.raises(ValueError, match="summary length.*exceeds"):
        SubtaskRecord(id="x", summary="s" * 65_537)


def test_completion_record_rejects_oversize_summary():
    with pytest.raises(ValueError, match="summary length.*exceeds"):
        CompletionRecord(summary="s" * 65_537)


# ============================================================================
# DSL parser bounds
# ============================================================================


def test_parse_rejects_oversize_source():
    src = "a" * (MAX_SOURCE_LEN + 1)
    with pytest.raises(FlowSyntaxError, match="exceeds MAX_SOURCE_LEN"):
        parse_flow(src)


def test_parse_rejects_too_deep_nesting():
    # MAX_PARSE_DEPTH = 64; build a >64-deep nested expression.
    deep = "(" * (MAX_PARSE_DEPTH + 5) + "a" + ")" * (MAX_PARSE_DEPTH + 5)
    with pytest.raises(FlowSyntaxError, match="nesting too deep"):
        parse_flow(deep)


def test_parse_rejects_too_many_nodes():
    # Build a flat sequence above MAX_NODES.
    nodes = " -> ".join([f"n{i}" for i in range(MAX_NODES + 50)])
    with pytest.raises(FlowSyntaxError, match="too many nodes"):
        parse_flow(nodes)


# ============================================================================
# In-memory engine eviction
# ============================================================================


def test_judging_engine_evicts_old_records(tmp_path):
    eng = JudgingEngine(tmp_path, max_records=3)
    j1 = eng.start("first", dimensions=["a"])
    j2 = eng.start("second", dimensions=["a"])
    j3 = eng.start("third", dimensions=["a"])
    j4 = eng.start("fourth", dimensions=["a"])
    # Internal cache holds at most 3 -- but disk has all 4.
    assert len(eng._judgings) == 3   # noqa: SLF001 -- enterprise check
    # Still retrievable on demand from disk.
    reloaded = eng.get(j1.id)
    assert reloaded is not None
    assert reloaded.subject == "first"


def test_verification_store_evicts_old_records(tmp_path):
    store = VerificationStore(tmp_path, max_records=2)
    a = store.start(fix_session="a")
    b = store.start(fix_session="b")
    c = store.start(fix_session="c")
    assert len(store._reports) == 2  # noqa: SLF001
    assert store.get(a.id).fix_session == "a"


def test_pgve_store_evicts_old_records(tmp_path):
    store = PgveStore(tmp_path, max_records=2)
    a = store.start(task_spec="a")
    b = store.start(task_spec="b")
    c = store.start(task_spec="c")
    assert len(store._sessions) == 2  # noqa: SLF001
    assert store.get(a.id).task_spec == "a"


def test_flow_store_evicts_old_records(tmp_path):
    store = FlowStore(tmp_path, max_records=2)
    a = store.start(source="x")
    b = store.start(source="y")
    c = store.start(source="z")
    assert len(store._flows) == 2  # noqa: SLF001
    assert store.get(a.id).source == "x"


# ============================================================================
# Schema-version > current emits warning
# ============================================================================


def _write_record(path, payload):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload), encoding="utf-8")


def test_judging_warns_on_future_schema(tmp_path, caplog):
    payload = {
        "schema_version": 99, "id": "judg-future",
        "subject": "x", "dimensions": ["a"], "judgments": [],
        "status": "open",
    }
    _write_record(tmp_path / "judg-future" / "judging.json", payload)
    with caplog.at_level(logging.WARNING):
        eng = JudgingEngine(tmp_path)
        eng.get("judg-future")
    assert any("schema_version 99" in r.message or "schema_version 99" in str(r)
               for r in caplog.records)


def test_verification_warns_on_future_schema(tmp_path, caplog):
    payload = {
        "schema_version": 99, "id": "verify-future",
        "fix_session": "x", "evidence": [], "status": "open",
    }
    _write_record(tmp_path / "verify-future" / "verification.json", payload)
    with caplog.at_level(logging.WARNING):
        store = VerificationStore(tmp_path)
        store.get("verify-future")
    assert any("schema_version 99" in r.message or "schema_version 99" in str(r)
               for r in caplog.records)


def test_pgve_warns_on_future_schema(tmp_path, caplog):
    payload = {
        "schema_version": 99, "id": "pgve-future",
        "task_spec": "x", "candidates": [], "evaluations": [],
        "status": "open", "max_candidates": 5,
    }
    _write_record(tmp_path / "pgve-future" / "pgve.json", payload)
    with caplog.at_level(logging.WARNING):
        store = PgveStore(tmp_path)
        store.get("pgve-future")
    assert any("schema_version 99" in r.message or "schema_version 99" in str(r)
               for r in caplog.records)


def test_flow_warns_on_future_schema(tmp_path, caplog):
    payload = {
        "schema_version": 99, "id": "flow-future",
        "source": "a", "root": parse_flow("a").to_dict(),
        "completed": [], "status": "open",
    }
    _write_record(tmp_path / "flow-future" / "flow.json", payload)
    with caplog.at_level(logging.WARNING):
        store = FlowStore(tmp_path)
        store.get("flow-future")
    assert any("schema_version 99" in r.message or "schema_version 99" in str(r)
               for r in caplog.records)
