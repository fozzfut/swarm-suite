"""Tests for CompletionTracker -- caps, idempotency, lifecycle."""

from __future__ import annotations

import pytest

from swarm_core.coordination import (
    CapExceededError,
    CompletionTracker,
)
from swarm_core.models.completion import (
    CompletionRecord,
    CompletionState,
    SubtaskRecord,
)


def test_tracker_starts_empty():
    t = CompletionTracker("sess-1")
    assert not t.is_complete()
    assert t.should_stop() == (False, "")
    state = t.state()
    assert state.session_id == "sess-1"
    assert state.subtasks == []
    assert state.completion is None
    assert state.consecutive_thinks == 0


def test_mark_subtask_done_appends_and_resets_thinks():
    t = CompletionTracker("sess-1")
    t.record_think()
    rec = t.mark_subtask_done("sub-1", summary="parsed file")
    assert rec.id == "sub-1"
    assert rec.loop_count == 1
    assert t.state().consecutive_thinks == 0
    assert len(t.state().subtasks) == 1


def test_mark_subtask_done_is_idempotent_on_id():
    t = CompletionTracker("sess-1")
    a = t.mark_subtask_done("sub-1", summary="first")
    b = t.mark_subtask_done("sub-1", summary="second-summary-ignored")
    assert a.id == b.id
    state = t.state()
    assert len(state.subtasks) == 1
    # Loop counter bumped on the kept record; new summary is dropped.
    assert state.subtasks[0].summary == "first"
    assert state.subtasks[0].loop_count == 2
    assert state.subtask_loop_counts["sub-1"] == 2


def test_mark_subtask_done_raises_on_max_subtasks():
    t = CompletionTracker("sess-1", max_subtasks=2)
    t.mark_subtask_done("a")
    t.mark_subtask_done("b")
    with pytest.raises(CapExceededError) as exc:
        t.mark_subtask_done("c")
    assert exc.value.cap == "max_subtasks"
    assert exc.value.limit == 2


def test_mark_subtask_done_raises_on_max_subtask_loops():
    t = CompletionTracker("sess-1", max_subtask_loops=2)
    t.mark_subtask_done("a")
    t.mark_subtask_done("a")  # loop=2 ok
    with pytest.raises(CapExceededError) as exc:
        t.mark_subtask_done("a")  # loop=3 trips
    assert exc.value.cap == "max_subtask_loops"


def test_complete_task_is_idempotent():
    t = CompletionTracker("sess-1")
    a = t.complete_task("done", outputs={"k": "v"})
    b = t.complete_task("different summary")
    assert a.id == b.id
    assert b.summary == "done"  # original kept
    assert b.outputs == {"k": "v"}
    assert t.is_complete()
    assert t.should_stop() == (True, "completed")


def test_subtask_done_after_complete_task_raises():
    t = CompletionTracker("sess-1")
    t.complete_task("done")
    with pytest.raises(ValueError, match="already-completed"):
        t.mark_subtask_done("sub-1")


def test_record_think_after_complete_raises():
    t = CompletionTracker("sess-1")
    t.complete_task("done")
    with pytest.raises(ValueError, match="already-completed"):
        t.record_think()


def test_record_think_caps():
    t = CompletionTracker("sess-1", max_consecutive_thinks=2)
    assert t.record_think() == 1
    assert t.record_think() == 2
    with pytest.raises(CapExceededError) as exc:
        t.record_think()
    assert exc.value.cap == "max_consecutive_thinks"


def test_record_action_resets_thinks():
    t = CompletionTracker("sess-1", max_consecutive_thinks=2)
    t.record_think()
    t.record_action()
    # After reset we can think again without tripping.
    assert t.record_think() == 1


def test_subtask_done_resets_thinks():
    t = CompletionTracker("sess-1", max_consecutive_thinks=2)
    t.record_think()
    t.mark_subtask_done("sub-1")
    assert t.state().consecutive_thinks == 0


def test_total_subtask_calls_counts_repeats():
    t = CompletionTracker("sess-1")
    t.mark_subtask_done("a")
    t.mark_subtask_done("a")
    t.mark_subtask_done("b")
    state = t.state()
    assert state.total_subtask_calls == 3
    assert len(state.subtasks) == 2


def test_state_returns_a_copy():
    t = CompletionTracker("sess-1")
    t.mark_subtask_done("a", outputs={"k": 1})
    snap = t.state()
    snap.subtasks[0].outputs["k"] = 999
    assert t.state().subtasks[0].outputs["k"] == 1


def test_restore_from_initial_state():
    initial = CompletionState(
        session_id="sess-1",
        subtasks=[SubtaskRecord(id="prev", summary="from disk", loop_count=2)],
        subtask_loop_counts={"prev": 2},
        total_subtask_calls=2,
    )
    t = CompletionTracker("sess-1", initial_state=initial)
    state = t.state()
    assert len(state.subtasks) == 1
    assert state.subtasks[0].id == "prev"
    assert state.subtasks[0].loop_count == 2


def test_initial_state_session_mismatch_raises():
    initial = CompletionState(session_id="other")
    with pytest.raises(ValueError, match="does not match"):
        CompletionTracker("sess-1", initial_state=initial)


def test_session_id_required():
    with pytest.raises(ValueError):
        CompletionTracker("")


def test_caps_validation():
    with pytest.raises(ValueError):
        CompletionTracker("sess-1", max_subtasks=0)
    with pytest.raises(ValueError):
        CompletionTracker("sess-1", max_subtask_loops=0)
    with pytest.raises(ValueError):
        CompletionTracker("sess-1", max_consecutive_thinks=-1)


def test_completion_state_round_trips():
    t = CompletionTracker("sess-1")
    t.mark_subtask_done("a", summary="parsed", outputs={"file": "x.py"})
    t.mark_subtask_done("a")
    t.mark_subtask_done("b")
    t.complete_task("all done")
    snap = t.state()
    rebuilt = CompletionState.from_dict(snap.to_dict())
    assert rebuilt.session_id == "sess-1"
    assert len(rebuilt.subtasks) == 2
    assert rebuilt.subtasks[0].id == "a"
    assert rebuilt.subtasks[0].loop_count == 2
    assert rebuilt.completion.summary == "all done"


def test_subtask_id_required():
    t = CompletionTracker("sess-1")
    with pytest.raises(ValueError):
        t.mark_subtask_done("")


def test_cap_exceeded_carries_diagnostics():
    t = CompletionTracker("sess-1", max_subtasks=1)
    t.mark_subtask_done("a")
    with pytest.raises(CapExceededError) as exc:
        t.mark_subtask_done("b")
    assert exc.value.cap == "max_subtasks"
    assert exc.value.current == 1
    assert exc.value.limit == 1
    assert exc.value.next_step
    # Subclass of ValueError so MCP wrapper maps to INVALID_PARAMS.
    assert isinstance(exc.value, ValueError)


def test_mark_subtask_done_defensively_copies_outputs():
    """Caller mutating its outputs dict must NOT affect stored state."""
    t = CompletionTracker("sess-1")
    caller_outputs = {"k": "original"}
    t.mark_subtask_done("a", outputs=caller_outputs)
    caller_outputs["k"] = "tampered"
    caller_outputs["new"] = "added"
    state = t.state()
    assert state.subtasks[0].outputs == {"k": "original"}
    assert "new" not in state.subtasks[0].outputs


def test_complete_task_defensively_copies_outputs():
    """Same defensive-copy contract on the terminal completion record."""
    t = CompletionTracker("sess-1")
    caller_outputs = {"diff": "patch-1"}
    t.complete_task("done", outputs=caller_outputs)
    caller_outputs["diff"] = "patch-2"
    state = t.state()
    assert state.completion.outputs == {"diff": "patch-1"}
