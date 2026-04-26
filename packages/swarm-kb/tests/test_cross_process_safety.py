"""Cross-process safety tests via real multiprocessing.

Spawns N child processes that hammer the SAME record concurrently and
asserts that no update is lost. Without `cross_process_lock` these
tests would fail (the read-modify-write race silently drops some
updates -- last-write-wins on the file). With the lock they pass
because each mutation observes the latest disk state before writing.

Uses the `spawn` start method so the tests run identically on Windows
(no fork) and POSIX. The worker functions are top-level module
functions so multiprocessing can pickle them.
"""

from __future__ import annotations

import json
import multiprocessing as mp
import os
from pathlib import Path

import pytest

from swarm_kb.completion_store import COMPLETION_FILE, CompletionStore
from swarm_kb.dsl import FlowStore, parse_flow
from swarm_kb.judging import JudgingEngine
from swarm_kb.pgve import PgveStore
from swarm_kb.verification import VerificationStore


# multiprocessing on Windows uses 'spawn' which re-imports this module
# in the child. Anything the worker needs at module scope must be
# picklable; functions defined here qualify.


def _completion_worker(args: tuple[str, str, str]) -> None:
    """Mark one subtask, then exit. Runs in a child process."""
    session_dir, session_id, subtask_id = args
    store = CompletionStore(Path(session_dir), session_id)
    store.mark_subtask_done(subtask_id, summary=f"by-pid-{os.getpid()}")


def _judging_worker(args: tuple[str, str, str, str]) -> None:
    """Submit one judgment to a shared judging."""
    judg_root, judging_id, judge, dimension = args
    eng = JudgingEngine(Path(judg_root))
    eng.judge(
        judging_id,
        judge=judge,
        dimension=dimension,
        verdict="pass",
        rationale=f"from pid-{os.getpid()}",
    )


def _verification_worker(args: tuple[str, str, str]) -> None:
    """Add one piece of evidence to a shared verification report."""
    verify_root, report_id, evidence_summary = args
    store = VerificationStore(Path(verify_root))
    store.add_evidence(
        report_id,
        kind="manual_note",
        summary=evidence_summary,
        data={"pid": os.getpid()},
    )


def _flow_worker(args: tuple[str, str, str]) -> None:
    """Mark one parallel step done in a shared flow."""
    flow_root, flow_id, step_id = args
    store = FlowStore(Path(flow_root))
    store.mark_done(flow_id, step_id)


# ---------------------------------------------------------------------------


@pytest.fixture(scope="module")
def mp_ctx():
    """Use 'spawn' explicitly so behaviour is identical on Windows + POSIX."""
    return mp.get_context("spawn")


def test_completion_store_no_lost_updates_under_real_processes(tmp_path, mp_ctx):
    """10 children each mark a distinct subtask; all must persist."""
    # Pre-create the session dir; CompletionStore expects to write into it.
    session_dir = tmp_path
    session_id = "sess-cross-1"

    # Spawn 10 children, each marking subtask-N.
    args = [(str(session_dir), session_id, f"sub-{i}") for i in range(10)]
    with mp_ctx.Pool(processes=4) as pool:
        pool.map(_completion_worker, args)

    # Read the final completion.json from disk; it must have all 10 subtasks.
    raw = json.loads((session_dir / COMPLETION_FILE).read_text(encoding="utf-8"))
    persisted_ids = {s["id"] for s in raw["subtasks"]}
    expected_ids = {f"sub-{i}" for i in range(10)}
    assert persisted_ids == expected_ids, (
        f"Lost updates: missing {expected_ids - persisted_ids}; "
        f"unexpected {persisted_ids - expected_ids}"
    )


def test_judging_engine_no_lost_judgments_under_real_processes(tmp_path, mp_ctx):
    """10 children each submit a judgment on distinct dimensions; all must persist."""
    judg_root = tmp_path
    # Parent creates the judging.
    eng = JudgingEngine(judg_root)
    dims = [f"d{i}" for i in range(10)]
    j = eng.start(subject="cross-proc test", dimensions=dims)

    args = [(str(judg_root), j.id, f"judge-{i}", f"d{i}") for i in range(10)]
    with mp_ctx.Pool(processes=4) as pool:
        pool.map(_judging_worker, args)

    # Reload from disk in the parent and assert all 10 judgments survived.
    fresh = JudgingEngine(judg_root)
    reloaded = fresh.get(j.id)
    assert reloaded is not None
    judged_dims = {jm.dimension for jm in reloaded.judgments}
    assert judged_dims == set(dims), (
        f"Lost judgments: missing {set(dims) - judged_dims}"
    )


def test_verification_store_no_lost_evidence_under_real_processes(tmp_path, mp_ctx):
    """10 children each add evidence to one report; all must persist."""
    verify_root = tmp_path
    store = VerificationStore(verify_root)
    r = store.start(fix_session="cross-proc-fix")

    args = [(str(verify_root), r.id, f"evidence-{i}") for i in range(10)]
    with mp_ctx.Pool(processes=4) as pool:
        pool.map(_verification_worker, args)

    fresh = VerificationStore(verify_root)
    reloaded = fresh.get(r.id)
    assert reloaded is not None
    summaries = {e.summary for e in reloaded.evidence}
    expected = {f"evidence-{i}" for i in range(10)}
    assert summaries == expected, (
        f"Lost evidence: missing {expected - summaries}"
    )


def test_flow_store_no_lost_steps_under_real_processes(tmp_path, mp_ctx):
    """10 parallel steps marked done across 10 children; all must register."""
    flow_root = tmp_path
    src = ", ".join(f"step{i}" for i in range(10))   # 10 parallel steps
    store = FlowStore(flow_root)
    flow = store.start(source=src)
    step_ids = [n.id for n in flow.next_steps()]

    args = [(str(flow_root), flow.id, step_id) for step_id in step_ids]
    with mp_ctx.Pool(processes=4) as pool:
        pool.map(_flow_worker, args)

    fresh = FlowStore(flow_root)
    reloaded = fresh.get(flow.id)
    assert reloaded is not None
    completed_ids = {r.step_id for r in reloaded.completed}
    assert completed_ids == set(step_ids), (
        f"Lost step completions: missing {set(step_ids) - completed_ids}"
    )
    assert reloaded.status == "completed"
