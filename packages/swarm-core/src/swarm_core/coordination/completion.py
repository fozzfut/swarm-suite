"""Completion tracker -- per-session self-direction with hard caps.

The tracker lets an agent declare "subtask N is done" and "the task
itself is done" via stable handles, so the host process can stop the
loop without parsing free-text. Hard caps prevent runaway: too many
distinct subtasks, too many re-marks of the same subtask, or too many
"think" steps without action all raise `CapExceededError`.

This is the in-memory counterpart to `swarm_kb.completion_store`, which
persists state to disk. The split mirrors `ClaimRegistry` (memory) +
caller-owned persistence -- the tracker only owns semantics, not I/O.

Caps are class-level constants and can be overridden per instance via
constructor args; tools that need different limits should pass them
explicitly rather than mutating the class attributes.
"""

from __future__ import annotations

import threading
from copy import deepcopy

from ..logging_setup import get_logger
from ..models.completion import (
    CompletionRecord,
    CompletionState,
    SubtaskRecord,
)
from ..timeutil import now_iso

_log = get_logger("core.completion")


# Default hard caps. Picked from kyegomez/swarms `max_loops="auto"` mode:
# 50 subtasks is large enough for a serious review pass but small enough
# to catch a runaway within a few seconds at LLM speed; 10 re-marks per
# subtask catches "agent kept saying done without progress"; 2 thinks
# without action is the swarms default for `max_consecutive_thinks`.
DEFAULT_MAX_SUBTASKS = 50
DEFAULT_MAX_SUBTASK_LOOPS = 10
DEFAULT_MAX_CONSECUTIVE_THINKS = 2


class CapExceededError(ValueError):
    """Hard cap exceeded -- the agent must stop or call complete_task.

    Subclasses ValueError so the MCP error wrapper maps it to
    INVALID_PARAMS (the client can recover by stopping). The message
    names the cap and the next step.
    """

    def __init__(self, cap: str, current: int, limit: int, next_step: str) -> None:
        self.cap = cap
        self.current = current
        self.limit = limit
        self.next_step = next_step
        super().__init__(
            f"completion cap '{cap}' exceeded: {current} >= {limit}. {next_step}"
        )


class CompletionTracker:
    """In-memory state machine for one session's completion lifecycle.

    Thread-safe. All mutating methods are idempotent on identity:
      * `mark_subtask_done(id=X)` returns the same first-seen record on
        repeat calls (with `loop_count` bumped) until the loop cap fires.
      * `complete_task(...)` returns the existing CompletionRecord on
        repeat calls; `summary` and `outputs` are NOT overwritten.

    `record_think()` does not return a value the caller needs to act on
    until the consecutive-thinks cap fires; it returns the new counter
    value purely for observability.
    """

    def __init__(
        self,
        session_id: str,
        *,
        max_subtasks: int = DEFAULT_MAX_SUBTASKS,
        max_subtask_loops: int = DEFAULT_MAX_SUBTASK_LOOPS,
        max_consecutive_thinks: int = DEFAULT_MAX_CONSECUTIVE_THINKS,
        initial_state: CompletionState | None = None,
    ) -> None:
        if not session_id:
            raise ValueError("session_id must be non-empty")
        if max_subtasks < 1 or max_subtask_loops < 1 or max_consecutive_thinks < 0:
            raise ValueError("caps must be positive (consecutive_thinks may be 0)")

        self._session_id = session_id
        self._max_subtasks = max_subtasks
        self._max_subtask_loops = max_subtask_loops
        self._max_consecutive_thinks = max_consecutive_thinks
        self._lock = threading.RLock()

        if initial_state is None:
            self._state = CompletionState(session_id=session_id)
        else:
            if initial_state.session_id != session_id:
                raise ValueError(
                    f"initial_state session_id {initial_state.session_id!r} "
                    f"does not match {session_id!r}"
                )
            self._state = initial_state

    # ---------------------------------------------------------------- read

    @property
    def session_id(self) -> str:
        return self._session_id

    def is_complete(self) -> bool:
        with self._lock:
            return self._state.completion is not None

    def should_stop(self) -> tuple[bool, str]:
        """True + reason if the agent should stop now.

        Reasons: "completed" (task done), or empty string if no stop.
        Cap exceedances raise instead of being reported here -- callers
        already get them at the action site.
        """
        with self._lock:
            if self._state.completion is not None:
                return True, "completed"
            return False, ""

    def state(self) -> CompletionState:
        """Return a deep copy of the current state."""
        with self._lock:
            return CompletionState.from_dict(self._state.to_dict())

    # ---------------------------------------------------------------- write

    def mark_subtask_done(
        self,
        subtask_id: str,
        summary: str = "",
        outputs: dict | None = None,
    ) -> SubtaskRecord:
        """Mark `subtask_id` done. Idempotent on id.

        First call: appends a SubtaskRecord, resets the consecutive-think
        counter, returns the new record.

        Repeat call (same id): bumps the existing record's `loop_count`
        and returns it; raises `CapExceededError` if the per-subtask loop
        cap is hit.

        Raises `CapExceededError` if a NEW id is given and the total
        subtask count is already at `max_subtasks`. Raises ValueError if
        called after `complete_task`.
        """
        if not subtask_id:
            raise ValueError("subtask_id must be non-empty")
        outputs = outputs or {}

        with self._lock:
            if self._state.completion is not None:
                raise ValueError(
                    "cannot mark_subtask_done on an already-completed session "
                    f"({self._session_id})"
                )

            self._state.total_subtask_calls += 1
            existing = self._find_subtask(subtask_id)

            if existing is not None:
                new_loop_count = existing.loop_count + 1
                if new_loop_count > self._max_subtask_loops:
                    raise CapExceededError(
                        cap="max_subtask_loops",
                        current=new_loop_count,
                        limit=self._max_subtask_loops,
                        next_step=(
                            f"subtask {subtask_id!r} re-marked too many times; "
                            "call complete_task or stop."
                        ),
                    )
                existing.loop_count = new_loop_count
                self._state.subtask_loop_counts[subtask_id] = new_loop_count
                self._state.consecutive_thinks = 0
                self._state.updated_at = now_iso()
                _log.debug(
                    "subtask %s re-marked (loop=%d) on %s",
                    subtask_id, new_loop_count, self._session_id,
                )
                return SubtaskRecord(
                    id=existing.id,
                    summary=existing.summary,
                    outputs=dict(existing.outputs),
                    completed_at=existing.completed_at,
                    loop_count=existing.loop_count,
                )

            if len(self._state.subtasks) >= self._max_subtasks:
                raise CapExceededError(
                    cap="max_subtasks",
                    current=len(self._state.subtasks),
                    limit=self._max_subtasks,
                    next_step="too many distinct subtasks; call complete_task or stop.",
                )

            # Defensive copy on the way INTO storage so the caller cannot
            # mutate the persisted dict via the original reference.
            record = SubtaskRecord(
                id=subtask_id, summary=summary, outputs=dict(outputs),
            )
            self._state.subtasks.append(record)
            self._state.subtask_loop_counts[subtask_id] = 1
            self._state.consecutive_thinks = 0
            self._state.updated_at = now_iso()
            _log.info("subtask %s done on %s", subtask_id, self._session_id)
            return SubtaskRecord(
                id=record.id,
                summary=record.summary,
                outputs=dict(record.outputs),
                completed_at=record.completed_at,
                loop_count=record.loop_count,
            )

    def complete_task(
        self,
        summary: str,
        outputs: dict | None = None,
    ) -> CompletionRecord:
        """Mark the whole task complete. Idempotent.

        Re-call returns the existing CompletionRecord untouched; the new
        `summary`/`outputs` arguments are dropped. This matches the MCP
        tool contract -- a retried call must not corrupt state.
        """
        outputs = outputs or {}
        with self._lock:
            if self._state.completion is not None:
                _log.info(
                    "complete_task on %s is a no-op (already completed)",
                    self._session_id,
                )
                return CompletionRecord.from_dict(self._state.completion.to_dict())

            # Defensive copy on the way INTO storage (mirrors the
            # per-subtask isolation in mark_subtask_done).
            record = CompletionRecord(summary=summary, outputs=dict(outputs))
            self._state.completion = record
            self._state.consecutive_thinks = 0
            self._state.updated_at = now_iso()
            _log.info(
                "task completed on %s (subtasks=%d, total_calls=%d)",
                self._session_id,
                len(self._state.subtasks),
                self._state.total_subtask_calls,
            )
            return CompletionRecord.from_dict(record.to_dict())

    def record_think(self) -> int:
        """Increment the consecutive-thinks counter; return new value.

        Raises CapExceededError if the new value exceeds the cap. The
        counter resets to 0 on `mark_subtask_done`, `complete_task`, or
        explicit `record_action`.
        """
        with self._lock:
            if self._state.completion is not None:
                raise ValueError(
                    "cannot record_think on an already-completed session "
                    f"({self._session_id})"
                )
            new_value = self._state.consecutive_thinks + 1
            if new_value > self._max_consecutive_thinks:
                raise CapExceededError(
                    cap="max_consecutive_thinks",
                    current=new_value,
                    limit=self._max_consecutive_thinks,
                    next_step=(
                        "too many thoughts without an action; "
                        "call mark_subtask_done or complete_task."
                    ),
                )
            self._state.consecutive_thinks = new_value
            self._state.updated_at = now_iso()
            return new_value

    def record_action(self) -> None:
        """Reset the consecutive-thinks counter without recording a subtask.

        Use when the agent does something side-effectful (writes a file,
        sends a message) that isn't itself a tracked subtask. Idempotent.
        """
        with self._lock:
            self._state.consecutive_thinks = 0
            self._state.updated_at = now_iso()

    # ---------------------------------------------------------------- caps

    @property
    def caps(self) -> dict[str, int]:
        return {
            "max_subtasks": self._max_subtasks,
            "max_subtask_loops": self._max_subtask_loops,
            "max_consecutive_thinks": self._max_consecutive_thinks,
        }

    # ---------------------------------------------------------------- internals

    def _find_subtask(self, subtask_id: str) -> SubtaskRecord | None:
        for s in self._state.subtasks:
            if s.id == subtask_id:
                return s
        return None
