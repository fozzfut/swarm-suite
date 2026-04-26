"""Tests for CompletionStore -- persistence, idempotency, event mirroring."""

from __future__ import annotations

import json

import pytest

from swarm_core.coordination import CapExceededError
from swarm_kb.completion_store import (
    COMPLETION_FILE,
    EVENTS_FILE,
    CompletionStore,
)


def test_store_persists_subtask(tmp_path):
    store = CompletionStore(tmp_path, "sess-1")
    store.mark_subtask_done("sub-1", summary="parsed")
    raw = json.loads((tmp_path / COMPLETION_FILE).read_text(encoding="utf-8"))
    assert raw["session_id"] == "sess-1"
    assert raw["subtasks"][0]["id"] == "sub-1"
    assert raw["subtasks"][0]["summary"] == "parsed"


def test_store_loads_existing_state(tmp_path):
    s1 = CompletionStore(tmp_path, "sess-1")
    s1.mark_subtask_done("sub-1", summary="initial")
    s1.mark_subtask_done("sub-1")  # loop=2

    # New store on the same dir should resume the prior state.
    s2 = CompletionStore(tmp_path, "sess-1")
    state = s2.state()
    assert len(state.subtasks) == 1
    assert state.subtasks[0].loop_count == 2
    assert state.total_subtask_calls == 2


def test_store_complete_task_is_idempotent(tmp_path):
    store = CompletionStore(tmp_path, "sess-1")
    a = store.complete_task("done", outputs={"x": 1})
    b = store.complete_task("different")
    assert a.id == b.id
    assert b.summary == "done"
    assert store.is_complete()


def test_store_caps_propagate_to_tracker(tmp_path):
    store = CompletionStore(tmp_path, "sess-1", max_subtasks=2)
    store.mark_subtask_done("a")
    store.mark_subtask_done("b")
    with pytest.raises(CapExceededError):
        store.mark_subtask_done("c")


def test_store_emits_events_when_events_jsonl_exists(tmp_path):
    # Pre-create events.jsonl as empty (mirroring real session lifecycle).
    (tmp_path / EVENTS_FILE).write_text("", encoding="utf-8")

    store = CompletionStore(tmp_path, "sess-1")
    store.mark_subtask_done("sub-1", summary="parsed")
    store.complete_task("done")

    lines = (tmp_path / EVENTS_FILE).read_text(encoding="utf-8").splitlines()
    assert len(lines) == 2
    types = [json.loads(l)["event_type"] for l in lines]
    assert types == ["subtask_done", "task_completed"]


def test_store_does_not_create_events_file_unsolicited(tmp_path):
    # No events.jsonl pre-existing -> no events file should be created.
    store = CompletionStore(tmp_path, "sess-1")
    store.mark_subtask_done("sub-1")
    assert not (tmp_path / EVENTS_FILE).exists()


def test_store_records_cap_event_on_overrun(tmp_path):
    (tmp_path / EVENTS_FILE).write_text("", encoding="utf-8")

    store = CompletionStore(tmp_path, "sess-1", max_subtasks=1)
    store.mark_subtask_done("a")
    with pytest.raises(CapExceededError):
        store.mark_subtask_done("b")

    lines = (tmp_path / EVENTS_FILE).read_text(encoding="utf-8").splitlines()
    types = [json.loads(l)["event_type"] for l in lines]
    assert "completion_cap_exceeded" in types
    cap_event = json.loads([l for l in lines if "cap_exceeded" in l][0])
    assert cap_event["payload"]["cap"] == "max_subtasks"
    assert cap_event["payload"]["operation"] == "mark_subtask_done"


def test_store_record_think_persists_counter(tmp_path):
    store = CompletionStore(tmp_path, "sess-1", max_consecutive_thinks=3)
    assert store.record_think() == 1
    assert store.record_think() == 2
    raw = json.loads((tmp_path / COMPLETION_FILE).read_text(encoding="utf-8"))
    assert raw["consecutive_thinks"] == 2


def test_store_record_action_resets_thinks(tmp_path):
    store = CompletionStore(tmp_path, "sess-1")
    store.record_think()
    store.record_action()
    raw = json.loads((tmp_path / COMPLETION_FILE).read_text(encoding="utf-8"))
    assert raw["consecutive_thinks"] == 0


def test_store_should_stop_after_complete(tmp_path):
    store = CompletionStore(tmp_path, "sess-1")
    assert store.should_stop() == (False, "")
    store.complete_task("done")
    assert store.should_stop() == (True, "completed")


def test_store_corrupt_completion_file_starts_fresh(tmp_path):
    (tmp_path / COMPLETION_FILE).write_text("not json", encoding="utf-8")
    store = CompletionStore(tmp_path, "sess-1")
    state = store.state()
    assert state.subtasks == []
    assert state.completion is None


def test_store_atomic_write_under_repeated_calls(tmp_path):
    store = CompletionStore(tmp_path, "sess-1")
    for i in range(10):
        store.mark_subtask_done(f"sub-{i}")
    raw = json.loads((tmp_path / COMPLETION_FILE).read_text(encoding="utf-8"))
    assert len(raw["subtasks"]) == 10
