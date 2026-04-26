"""Reaction model -- expert reacts to another expert's finding/proposal."""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum

from ..ids import generate_id
from ..timeutil import now_iso


class ReactionType(str, Enum):
    """Cross-expert reaction kinds.

    Tools MAY extend this enum by subclassing (`class FixReactionType(str, Enum)`)
    when they need additional verbs (`approve` / `reject`), but the four
    base verbs below appear in every tool's storage.
    """

    CONFIRM = "confirm"
    DISPUTE = "dispute"
    EXTEND = "extend"
    DUPLICATE = "duplicate"


@dataclass
class Reaction:
    """An expert's reaction to a finding or proposal.

    Generic enough to serialize for any tool. Tool-specific extras go in
    `extra: dict` rather than expanding the base class.
    """

    session_id: str
    target_id: str           # finding_id, proposal_id, etc.
    expert_role: str
    reaction: ReactionType
    reason: str = ""
    related_target_id: str = ""
    extra: dict = field(default_factory=dict)
    id: str = ""
    created_at: str = ""

    def __post_init__(self) -> None:
        if not self.id:
            self.id = generate_id("r")
        if not self.created_at:
            self.created_at = now_iso()

    def to_dict(self) -> dict:
        return {
            "id": self.id,
            "session_id": self.session_id,
            "target_id": self.target_id,
            "expert_role": self.expert_role,
            "reaction": self.reaction.value,
            "reason": self.reason,
            "related_target_id": self.related_target_id,
            "extra": dict(self.extra),
            "created_at": self.created_at,
        }

    @classmethod
    def from_dict(cls, d: dict) -> "Reaction":
        return cls(
            id=d.get("id", ""),
            session_id=d["session_id"],
            target_id=d["target_id"],
            expert_role=d["expert_role"],
            reaction=ReactionType(d["reaction"]),
            reason=d.get("reason", ""),
            related_target_id=d.get("related_target_id", ""),
            extra=dict(d.get("extra", {})),
            created_at=d.get("created_at", ""),
        )
