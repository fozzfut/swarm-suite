"""Message model -- agent-to-agent communication inside a session."""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum

from ..ids import generate_id
from ..timeutil import now_iso


class MessageType(str, Enum):
    """Direction of an agent message."""

    DIRECT = "direct"        # one agent -> one agent
    BROADCAST = "broadcast"  # one agent -> all agents
    QUERY = "query"          # question to all, expects responses
    RESPONSE = "response"    # answer to a query


@dataclass
class Message:
    """An agent-to-agent message attached to a session.

    `to_agent="*"` means broadcast. `context` carries structured links
    (finding_id, file, line range) so the recipient can act without
    having to re-query the store.
    """

    session_id: str
    from_agent: str
    to_agent: str
    message_type: MessageType
    content: str
    in_reply_to: str = ""
    urgent: bool = False
    context: dict = field(default_factory=dict)
    id: str = ""
    created_at: str = ""

    def __post_init__(self) -> None:
        if not self.id:
            self.id = generate_id("m", length=4)
        if not self.created_at:
            self.created_at = now_iso()

    def to_dict(self) -> dict:
        return {
            "id": self.id,
            "session_id": self.session_id,
            "from_agent": self.from_agent,
            "to_agent": self.to_agent,
            "message_type": self.message_type.value,
            "content": self.content,
            "in_reply_to": self.in_reply_to,
            "urgent": self.urgent,
            "context": dict(self.context),
            "created_at": self.created_at,
        }

    @classmethod
    def from_dict(cls, d: dict) -> "Message":
        return cls(
            id=d.get("id", ""),
            session_id=d["session_id"],
            from_agent=d["from_agent"],
            to_agent=d["to_agent"],
            message_type=MessageType(d["message_type"]),
            content=d["content"],
            in_reply_to=d.get("in_reply_to", ""),
            urgent=d.get("urgent", False),
            context=dict(d.get("context", {})),
            created_at=d.get("created_at", ""),
        )
