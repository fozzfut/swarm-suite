"""Per-session persistence for `CompletionTracker`.

Stores `completion.json` next to `meta.json` in a session directory and
keeps an in-memory tracker in sync. Also appends a one-line entry to
`events.jsonl` (if it exists) for every state change so subscribers
that watch the session timeline see completion events without a
separate channel.

This is the bridge between swarm-core's pure tracker and disk; the
tracker itself owns the cap semantics.

CONCURRENCY (READ THIS BEFORE TOUCHING):
The store is safe across processes via a cross-process file lock on a
sibling `completion.lock`. Each mutating call:
  1. Acquires the per-instance threading.RLock (same-process serialise).
  2. Acquires the cross-process file lock via portalocker.
  3. Force-reloads from disk so we observe writes by sibling processes.
  4. Mutates the freshly-loaded tracker.
  5. atomic_write_text persists; lock released on context exit.

This protects against the lost-update race when two MCP servers (or
two Claude Code instances + a CI job, ...) hit the same session in
parallel. The lock is per-session (sibling .lock file), so different
sessions run independently.
"""

from __future__ import annotations

import json
import logging
import threading
from pathlib import Path

from swarm_core.coordination import CompletionTracker, CapExceededError
from swarm_core.io import append_jsonl_line, atomic_write_text
from swarm_core.models.completion import (
    EVENT_SUBTASK_DONE,
    EVENT_TASK_COMPLETED,
    EVENT_THINK_RECORDED,
    EVENT_CAP_EXCEEDED,
    CompletionRecord,
    CompletionState,
    SubtaskRecord,
)
from swarm_core.models.event import Event
from swarm_core.timeutil import now_iso

from ._filelock import cross_process_lock, lock_path_for

_log = logging.getLogger("swarm_kb.completion_store")

COMPLETION_FILE = "completion.json"
EVENTS_FILE = "events.jsonl"


class CompletionStore:
    """Disk-backed wrapper around a `CompletionTracker`.

    Constructed with the absolute session directory. Loads existing
    state from `completion.json` if present; otherwise starts empty.
    """

    def __init__(
        self,
        session_dir: Path,
        session_id: str,
        *,
        max_subtasks: int | None = None,
        max_subtask_loops: int | None = None,
        max_consecutive_thinks: int | None = None,
    ) -> None:
        self._session_dir = Path(session_dir)
        self._session_id = session_id
        self._completion_path = self._session_dir / COMPLETION_FILE
        self._lock_path = lock_path_for(self._completion_path)
        self._events_path = self._session_dir / EVENTS_FILE
        self._lock = threading.Lock()

        # Tracker construction kwargs are remembered so we can rebuild
        # the tracker from disk inside the cross-process lock when a
        # sibling process has updated state since our last load.
        self._tracker_kwargs: dict = {}
        if max_subtasks is not None:
            self._tracker_kwargs["max_subtasks"] = max_subtasks
        if max_subtask_loops is not None:
            self._tracker_kwargs["max_subtask_loops"] = max_subtask_loops
        if max_consecutive_thinks is not None:
            self._tracker_kwargs["max_consecutive_thinks"] = max_consecutive_thinks

        # Initial load.
        self._tracker = self._build_tracker(self._load_state())

    def _build_tracker(self, state) -> CompletionTracker:
        return CompletionTracker(
            session_id=self._session_id,
            initial_state=state,
            **self._tracker_kwargs,
        )

    def _force_reload_tracker(self) -> None:
        """Rebuild the in-memory tracker from disk.

        MUST be called inside the cross-process lock. Replaces self._tracker
        so that subsequent mutations apply to the freshest state.
        """
        self._tracker = self._build_tracker(self._load_state())

    # ---------------------------------------------------------------- read

    @property
    def session_id(self) -> str:
        return self._session_id

    @property
    def session_dir(self) -> Path:
        return self._session_dir

    @property
    def caps(self) -> dict[str, int]:
        return self._tracker.caps

    def state(self) -> CompletionState:
        return self._tracker.state()

    def is_complete(self) -> bool:
        return self._tracker.is_complete()

    def should_stop(self) -> tuple[bool, str]:
        return self._tracker.should_stop()

    # ---------------------------------------------------------------- write

    def mark_subtask_done(
        self,
        subtask_id: str,
        summary: str = "",
        outputs: dict | None = None,
    ) -> SubtaskRecord:
        with self._lock, cross_process_lock(self._lock_path):
            self._force_reload_tracker()
            try:
                record = self._tracker.mark_subtask_done(
                    subtask_id, summary=summary, outputs=outputs,
                )
            except CapExceededError as exc:
                self._emit_event(EVENT_CAP_EXCEEDED, {
                    "cap": exc.cap, "current": exc.current, "limit": exc.limit,
                    "next_step": exc.next_step,
                    "operation": "mark_subtask_done", "subtask_id": subtask_id,
                })
                raise
            self._persist()
            self._emit_event(EVENT_SUBTASK_DONE, {
                "subtask_id": record.id,
                "loop_count": record.loop_count,
                "summary": record.summary,
            })
            return record

    def complete_task(
        self,
        summary: str,
        outputs: dict | None = None,
    ) -> CompletionRecord:
        with self._lock, cross_process_lock(self._lock_path):
            self._force_reload_tracker()
            already = self._tracker.is_complete()
            record = self._tracker.complete_task(summary, outputs=outputs)
            if not already:
                self._persist()
                self._emit_event(EVENT_TASK_COMPLETED, {
                    "completion_id": record.id,
                    "summary": record.summary,
                    "subtasks": len(self._tracker.state().subtasks),
                })
            return record

    def record_think(self) -> int:
        with self._lock, cross_process_lock(self._lock_path):
            self._force_reload_tracker()
            try:
                value = self._tracker.record_think()
            except CapExceededError as exc:
                self._emit_event(EVENT_CAP_EXCEEDED, {
                    "cap": exc.cap, "current": exc.current, "limit": exc.limit,
                    "next_step": exc.next_step,
                    "operation": "record_think",
                })
                raise
            self._persist()
            self._emit_event(EVENT_THINK_RECORDED, {"counter": value})
            return value

    def record_action(self) -> None:
        with self._lock, cross_process_lock(self._lock_path):
            self._force_reload_tracker()
            self._tracker.record_action()
            self._persist()

    # ---------------------------------------------------------------- internals

    def _load_state(self) -> CompletionState | None:
        if not self._completion_path.exists():
            return None
        try:
            raw = json.loads(self._completion_path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError) as exc:
            _log.warning(
                "Failed to load %s: %s; starting fresh state",
                self._completion_path, exc,
            )
            return None
        try:
            return CompletionState.from_dict(raw)
        except (KeyError, TypeError, ValueError) as exc:
            _log.warning(
                "Invalid completion state in %s: %s; starting fresh",
                self._completion_path, exc,
            )
            return None

    def _persist(self) -> None:
        state = self._tracker.state()
        self._session_dir.mkdir(parents=True, exist_ok=True)
        atomic_write_text(
            self._completion_path,
            json.dumps(state.to_dict(), indent=2, ensure_ascii=False),
        )

    def _emit_event(self, event_type: str, payload: dict) -> None:
        if not self._events_path.exists():
            # Don't create a session-level events log just for completion;
            # only mirror into one if the session already keeps a timeline.
            return
        event = Event(
            session_id=self._session_id,
            event_type=event_type,
            payload=dict(payload),
            timestamp=now_iso(),
        )
        try:
            append_jsonl_line(
                self._events_path,
                json.dumps(event.to_dict(), ensure_ascii=False),
            )
        except OSError as exc:
            _log.warning(
                "Failed to append %s event to %s: %s",
                event_type, self._events_path, exc,
            )


def open_store(
    session_dir: Path,
    session_id: str,
    **caps: int,
) -> CompletionStore:
    """Convenience constructor; identical to `CompletionStore(...)`.

    Reserved for API symmetry with other swarm-kb stores
    (`get_finding_reader`, `DecisionStore`, etc.).
    """
    return CompletionStore(session_dir, session_id, **caps)
