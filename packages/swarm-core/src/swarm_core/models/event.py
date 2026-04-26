"""Event model -- session timeline entries published on state change."""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum

from ..ids import generate_id
from ..timeutil import now_iso


class EventType(str, Enum):
    """Generic session events shared across tools.

    Tool-specific events live in `<tool>.events` with their own enum;
    the base set below is what every tool is expected to publish.
    """

    SESSION_STARTED = "session_started"
    SESSION_ENDED = "session_ended"
    PHASE_DONE = "phase_done"
    MESSAGE = "message"
    BROADCAST = "broadcast"


@dataclass
class Event:
    """A timeline entry for a session.

    `event_type` is `str` (not the `EventType` enum) so tools can publish
    their own event types without subclassing. Use `EventType.X.value`
    when publishing a base event.
    """

    session_id: str
    event_type: str
    payload: dict = field(default_factory=dict)
    id: str = ""
    timestamp: str = ""

    def __post_init__(self) -> None:
        if not self.id:
            self.id = generate_id("e", length=4)
        if not self.timestamp:
            self.timestamp = now_iso()

    def to_dict(self) -> dict:
        return {
            "id": self.id,
            "session_id": self.session_id,
            "event_type": self.event_type,
            "payload": dict(self.payload),
            "timestamp": self.timestamp,
        }

    @classmethod
    def from_dict(cls, d: dict) -> "Event":
        return cls(
            id=d.get("id", ""),
            session_id=d["session_id"],
            event_type=d["event_type"],
            payload=dict(d.get("payload", {})),
            timestamp=d.get("timestamp", ""),
        )
