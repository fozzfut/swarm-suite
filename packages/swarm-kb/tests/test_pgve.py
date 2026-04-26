"""Tests for the planner-generator-evaluator loop store."""

from __future__ import annotations

import json

import pytest

from swarm_kb.pgve import (
    DEFAULT_MAX_CANDIDATES,
    Candidate,
    Evaluation,
    PgveSession,
    PgveStore,
    VALID_VERDICTS,
)


def test_session_requires_task_spec():
    with pytest.raises(ValueError, match="non-empty"):
        PgveSession(task_spec="")


def test_session_max_candidates_validated():
    with pytest.raises(ValueError, match=">= 1"):
        PgveSession(task_spec="x", max_candidates=0)


def test_evaluation_verdict_validated():
    with pytest.raises(ValueError, match="not in"):
        Evaluation(verdict="brilliant")


def test_store_start_persists(tmp_path):
    store = PgveStore(tmp_path)
    s = store.start(task_spec="produce a fix for f-1", max_candidates=3)
    raw = json.loads((tmp_path / s.id / "pgve.json").read_text(encoding="utf-8"))
    assert raw["task_spec"] == "produce a fix for f-1"
    assert raw["max_candidates"] == 3
    assert raw["status"] == "open"


def test_submit_candidate_appends(tmp_path):
    store = PgveStore(tmp_path)
    s = store.start(task_spec="x")
    cand = store.submit_candidate(
        s.id, generator="gen-1", content="patch v1", payload={"diff": "..."}
    )
    assert cand.previous_feedback == ""  # first candidate
    reloaded = store.get(s.id)
    assert len(reloaded.candidates) == 1
    assert reloaded.candidates[0].generator == "gen-1"


def test_submit_carries_previous_feedback(tmp_path):
    store = PgveStore(tmp_path)
    s = store.start(task_spec="x")
    store.submit_candidate(s.id, generator="g", content="v1")
    store.evaluate(s.id, evaluator="e", verdict="revise", feedback="needs lock")
    cand = store.submit_candidate(s.id, generator="g", content="v2")
    assert cand.previous_feedback == "needs lock"


def test_evaluate_accepted_finalises(tmp_path):
    store = PgveStore(tmp_path)
    s = store.start(task_spec="x")
    store.submit_candidate(s.id, generator="g", content="v1")
    store.evaluate(s.id, evaluator="e", verdict="accepted", feedback="lgtm")
    reloaded = store.get(s.id)
    assert reloaded.status == "accepted"
    assert reloaded.accepted_candidate_id == reloaded.candidates[0].id


def test_evaluate_rejected_marks_rejected(tmp_path):
    store = PgveStore(tmp_path)
    s = store.start(task_spec="x")
    store.submit_candidate(s.id, generator="g", content="v1")
    store.evaluate(s.id, evaluator="e", verdict="rejected", feedback="approach wrong")
    reloaded = store.get(s.id)
    assert reloaded.status == "rejected"


def test_revise_with_no_budget_marks_exhausted(tmp_path):
    store = PgveStore(tmp_path)
    s = store.start(task_spec="x", max_candidates=1)
    store.submit_candidate(s.id, generator="g", content="v1")
    store.evaluate(s.id, evaluator="e", verdict="revise", feedback="more")
    reloaded = store.get(s.id)
    assert reloaded.status == "exhausted"
    # Budget = 0, so a follow-up submit should be rejected.
    with pytest.raises(ValueError, match="not open"):
        store.submit_candidate(reloaded.id, generator="g", content="v2")


def test_submit_after_accepted_raises(tmp_path):
    store = PgveStore(tmp_path)
    s = store.start(task_spec="x")
    store.submit_candidate(s.id, generator="g", content="v1")
    store.evaluate(s.id, evaluator="e", verdict="accepted", feedback="ok")
    with pytest.raises(ValueError, match="not open"):
        store.submit_candidate(s.id, generator="g", content="v2")


def test_evaluate_without_candidate_raises(tmp_path):
    store = PgveStore(tmp_path)
    s = store.start(task_spec="x")
    with pytest.raises(ValueError, match="no candidate"):
        store.evaluate(s.id, evaluator="e", verdict="accepted", feedback="ok")


def test_remaining_budget_decreases(tmp_path):
    store = PgveStore(tmp_path)
    s = store.start(task_spec="x", max_candidates=3)
    assert store.get(s.id).remaining_budget() == 3
    store.submit_candidate(s.id, generator="g", content="v1")
    assert store.get(s.id).remaining_budget() == 2


def test_cancel(tmp_path):
    store = PgveStore(tmp_path)
    s = store.start(task_spec="x")
    store.cancel(s.id)
    assert store.get(s.id).status == "cancelled"


def test_list_filters_by_status(tmp_path):
    store = PgveStore(tmp_path)
    s1 = store.start(task_spec="x")
    s2 = store.start(task_spec="y")
    store.submit_candidate(s2.id, generator="g", content="v1")
    store.evaluate(s2.id, evaluator="e", verdict="accepted", feedback="ok")
    open_only = store.list_all(status="open")
    accepted_only = store.list_all(status="accepted")
    assert {s.id for s in open_only} == {s1.id}
    assert {s.id for s in accepted_only} == {s2.id}


def test_round_trip_via_disk(tmp_path):
    store = PgveStore(tmp_path)
    s = store.start(task_spec="x")
    store.submit_candidate(s.id, generator="g", content="v1")
    store.evaluate(s.id, evaluator="e", verdict="revise", feedback="more please")
    store.submit_candidate(s.id, generator="g", content="v2")
    store.evaluate(s.id, evaluator="e", verdict="accepted", feedback="thanks")

    fresh = PgveStore(tmp_path)
    reloaded = fresh.get(s.id)
    assert reloaded.status == "accepted"
    assert len(reloaded.candidates) == 2
    assert reloaded.candidates[1].previous_feedback == "more please"


def test_caller_mutating_payload_does_not_affect_storage(tmp_path):
    store = PgveStore(tmp_path)
    s = store.start(task_spec="x")
    payload = {"k": "v"}
    store.submit_candidate(s.id, generator="g", content="c", payload=payload)
    payload["k"] = "tampered"
    reloaded = store.get(s.id)
    assert reloaded.candidates[0].payload == {"k": "v"}


def test_default_max_candidates_constant():
    assert DEFAULT_MAX_CANDIDATES >= 1
