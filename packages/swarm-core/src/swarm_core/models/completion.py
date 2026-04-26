"""Completion models -- self-direction events for the completion tracker.

`SubtaskRecord` is one step the agent says it has finished.
`CompletionRecord` is the agent's "the whole task is done" signal.
`CompletionState` is the persisted snapshot of a tracker.

These are dataclasses, not enums, because they carry payload (summary,
outputs). The corresponding event-type strings live alongside the
generic `EventType` enum so subscribers can filter on them without
importing this module.
"""

from __future__ import annotations

from dataclasses import dataclass, field

from ..ids import generate_id
from ..timeutil import now_iso


COMPLETION_SCHEMA_VERSION = 1

# Input bounds. Mirrored in swarm_kb._limits but defined here too so
# swarm-core has no dependency on swarm-kb. If you tune one, tune both.
_MAX_TEXT_LEN = 65_536

# Event-type strings emitted into events.jsonl when a session has one.
EVENT_SUBTASK_DONE = "subtask_done"
EVENT_TASK_COMPLETED = "task_completed"
EVENT_THINK_RECORDED = "think_recorded"
EVENT_CAP_EXCEEDED = "completion_cap_exceeded"


@dataclass
class SubtaskRecord:
    """One subtask the agent reports finished.

    `id` is the agent-supplied stable handle (so re-marking the same
    subtask is idempotent). `loop_count` tracks how many times this
    same id has been marked done.
    """

    id: str
    summary: str = ""
    outputs: dict = field(default_factory=dict)
    completed_at: str = ""
    loop_count: int = 1

    def __post_init__(self) -> None:
        if not self.completed_at:
            self.completed_at = now_iso()
        if len(self.summary) > _MAX_TEXT_LEN:
            raise ValueError(
                f"SubtaskRecord summary length {len(self.summary)} exceeds {_MAX_TEXT_LEN}"
            )

    def to_dict(self) -> dict:
        return {
            "id": self.id,
            "summary": self.summary,
            "outputs": dict(self.outputs),
            "completed_at": self.completed_at,
            "loop_count": self.loop_count,
        }

    @classmethod
    def from_dict(cls, d: dict) -> "SubtaskRecord":
        return cls(
            id=d["id"],
            summary=d.get("summary", ""),
            outputs=dict(d.get("outputs", {})),
            completed_at=d.get("completed_at", ""),
            loop_count=int(d.get("loop_count", 1)),
        )


@dataclass
class CompletionRecord:
    """The agent's terminal "task done" signal.

    Idempotent at the tracker layer: re-emitting returns the existing
    record without overwriting `summary` or `completed_at`.
    """

    summary: str
    outputs: dict = field(default_factory=dict)
    completed_at: str = ""
    id: str = ""

    def __post_init__(self) -> None:
        if not self.id:
            self.id = generate_id("done", length=2)
        if not self.completed_at:
            self.completed_at = now_iso()
        if len(self.summary) > _MAX_TEXT_LEN:
            raise ValueError(
                f"CompletionRecord summary length {len(self.summary)} exceeds {_MAX_TEXT_LEN}"
            )

    def to_dict(self) -> dict:
        return {
            "id": self.id,
            "summary": self.summary,
            "outputs": dict(self.outputs),
            "completed_at": self.completed_at,
        }

    @classmethod
    def from_dict(cls, d: dict) -> "CompletionRecord":
        return cls(
            id=d.get("id", ""),
            summary=d.get("summary", ""),
            outputs=dict(d.get("outputs", {})),
            completed_at=d.get("completed_at", ""),
        )


@dataclass
class CompletionState:
    """Persisted snapshot of a `CompletionTracker`.

    `subtasks` holds the *first* record per subtask id in completion
    order; re-marks of the same id only bump `loop_count` on the
    existing record. `subtask_loop_counts` mirrors that for fast lookup.
    `total_subtask_calls` counts every call (including no-op re-marks);
    useful as a runaway signal independent of distinct subtask count.
    """

    session_id: str
    subtasks: list[SubtaskRecord] = field(default_factory=list)
    subtask_loop_counts: dict[str, int] = field(default_factory=dict)
    completion: CompletionRecord | None = None
    consecutive_thinks: int = 0
    total_subtask_calls: int = 0
    schema_version: int = COMPLETION_SCHEMA_VERSION
    created_at: str = ""
    updated_at: str = ""

    def __post_init__(self) -> None:
        ts = now_iso()
        if not self.created_at:
            self.created_at = ts
        if not self.updated_at:
            self.updated_at = ts

    def to_dict(self) -> dict:
        return {
            "schema_version": self.schema_version,
            "session_id": self.session_id,
            "subtasks": [s.to_dict() for s in self.subtasks],
            "subtask_loop_counts": dict(self.subtask_loop_counts),
            "completion": self.completion.to_dict() if self.completion else None,
            "consecutive_thinks": self.consecutive_thinks,
            "total_subtask_calls": self.total_subtask_calls,
            "created_at": self.created_at,
            "updated_at": self.updated_at,
        }

    @classmethod
    def from_dict(cls, d: dict) -> "CompletionState":
        completion = d.get("completion")
        return cls(
            session_id=d["session_id"],
            subtasks=[SubtaskRecord.from_dict(s) for s in d.get("subtasks", [])],
            subtask_loop_counts=dict(d.get("subtask_loop_counts", {})),
            completion=CompletionRecord.from_dict(completion) if completion else None,
            consecutive_thinks=int(d.get("consecutive_thinks", 0)),
            total_subtask_calls=int(d.get("total_subtask_calls", 0)),
            schema_version=int(d.get("schema_version", COMPLETION_SCHEMA_VERSION)),
            created_at=d.get("created_at", ""),
            updated_at=d.get("updated_at", ""),
        )
