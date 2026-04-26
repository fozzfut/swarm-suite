"""Message model -- agent-to-agent communication inside a session.

Carries the swarms-style structured triple alongside the legacy
`content`/`context` fields:
  * `content` -- the message itself (what the agent is saying right now)
  * `background` -- persistent task context (overall goal / role / inputs)
  * `intermediate_output` -- the most recent upstream result the
    receiver needs to act on without re-querying the store

A late-joining or restarted agent can resume from one Message without
rehydrating prior state from JSONL because all three layers are in the
payload. `context` remains for legacy structured links (finding_id,
file, line range) that don't fit cleanly into background or output.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum

from ..ids import generate_id
from ..logging_setup import get_logger
from ..timeutil import now_iso

_log = get_logger("core.models.message")


class MessageType(str, Enum):
    """Direction of an agent message."""

    DIRECT = "direct"        # one agent -> one agent
    BROADCAST = "broadcast"  # one agent -> all agents
    QUERY = "query"          # question to all, expects responses
    RESPONSE = "response"    # answer to a query


MESSAGE_SCHEMA_VERSION = 2  # bump: added background + intermediate_output


@dataclass
class Message:
    """An agent-to-agent message attached to a session.

    `to_agent="*"` means broadcast. The structured triple is
    `(content, background, intermediate_output)`; older callers that
    set only `content` keep working since the new fields default empty.

    `schema_version` lets readers tell new from old payloads; per
    CLAUDE.md, readers MUST tolerate >= their own and ignore unknown
    keys.
    """

    session_id: str
    from_agent: str
    to_agent: str
    message_type: MessageType
    content: str
    in_reply_to: str = ""
    urgent: bool = False
    context: dict = field(default_factory=dict)
    background: dict = field(default_factory=dict)
    intermediate_output: dict = field(default_factory=dict)
    schema_version: int = MESSAGE_SCHEMA_VERSION
    id: str = ""
    created_at: str = ""

    def __post_init__(self) -> None:
        if not self.id:
            self.id = generate_id("m", length=4)
        if not self.created_at:
            self.created_at = now_iso()

    def to_dict(self) -> dict:
        return {
            "schema_version": self.schema_version,
            "id": self.id,
            "session_id": self.session_id,
            "from_agent": self.from_agent,
            "to_agent": self.to_agent,
            "message_type": self.message_type.value,
            "content": self.content,
            "in_reply_to": self.in_reply_to,
            "urgent": self.urgent,
            "context": dict(self.context),
            "background": dict(self.background),
            "intermediate_output": dict(self.intermediate_output),
            "created_at": self.created_at,
        }

    @classmethod
    def from_dict(cls, d: dict) -> "Message":
        v = int(d.get("schema_version", 1))
        if v > MESSAGE_SCHEMA_VERSION:
            # Per CLAUDE.md: tolerate >= our own, log a warning so the
            # gap is visible when fields go missing in the loaded object.
            _log.warning(
                "Message schema_version %d > current %d; reading what we understand",
                v, MESSAGE_SCHEMA_VERSION,
            )
        return cls(
            schema_version=v,
            id=d.get("id", ""),
            session_id=d["session_id"],
            from_agent=d["from_agent"],
            to_agent=d["to_agent"],
            message_type=MessageType(d["message_type"]),
            content=d["content"],
            in_reply_to=d.get("in_reply_to", ""),
            urgent=d.get("urgent", False),
            context=dict(d.get("context", {})),
            background=dict(d.get("background", {})),
            intermediate_output=dict(d.get("intermediate_output", {})),
            created_at=d.get("created_at", ""),
        )

    def to_structured_payload(self) -> dict:
        """Return just the (content, background, intermediate_output) triple.

        Use this when emitting to MessageBus topics where subscribers
        only care about the structured triple, not the wrapper metadata.
        """
        return {
            "content": self.content,
            "background": dict(self.background),
            "intermediate_output": dict(self.intermediate_output),
        }
