"""Data models for FixSwarm -- FixAction, FixPlan, FixResult, and multi-agent collaboration types."""

from __future__ import annotations

import secrets
from dataclasses import dataclass, field
from enum import Enum
from typing import Optional


# ---------------------------------------------------------------------------
# Enums -- original
# ---------------------------------------------------------------------------

class FixActionType(str, Enum):
    """The kind of text transformation to apply."""

    REPLACE = "replace"
    INSERT = "insert"
    DELETE = "delete"


class Severity(str, Enum):
    """Mirror of ReviewSwarm severity levels, ordered high-to-low."""

    CRITICAL = "critical"
    HIGH = "high"
    MEDIUM = "medium"
    LOW = "low"
    INFO = "info"


# Severity ordering: lower index == higher priority.
SEVERITY_ORDER: list[Severity] = [
    Severity.CRITICAL,
    Severity.HIGH,
    Severity.MEDIUM,
    Severity.LOW,
    Severity.INFO,
]


def severity_at_least(sev: Severity, threshold: Severity) -> bool:
    """Return True if *sev* is at least as severe as *threshold*."""
    try:
        return SEVERITY_ORDER.index(sev) <= SEVERITY_ORDER.index(threshold)
    except ValueError:
        return False


# ---------------------------------------------------------------------------
# Enums -- multi-agent collaboration
# ---------------------------------------------------------------------------

class ProposalStatus(str, Enum):
    PROPOSED = "proposed"
    APPROVED = "approved"
    REJECTED = "rejected"
    APPLIED = "applied"
    FAILED = "failed"
    VERIFIED = "verified"


class ReactionType(str, Enum):
    APPROVE = "approve"
    REJECT = "reject"
    SUGGEST_ALTERNATIVE = "suggest_alternative"
    REQUEST_EVIDENCE = "request_evidence"


class MessageType(str, Enum):
    DIRECT = "direct"
    BROADCAST = "broadcast"
    QUERY = "query"
    RESPONSE = "response"


class ClaimStatus(str, Enum):
    ACTIVE = "active"
    RELEASED = "released"


class EventType(str, Enum):
    FIX_PROPOSED = "fix_proposed"
    FIX_APPROVED = "fix_approved"
    FIX_REJECTED = "fix_rejected"
    FIX_APPLIED = "fix_applied"
    FIX_FAILED = "fix_failed"
    FIX_VERIFIED = "fix_verified"
    REACTION_ADDED = "reaction_added"
    FINDING_CLAIMED = "finding_claimed"
    FINDING_RELEASED = "finding_released"
    MESSAGE = "message"
    MESSAGE_SENT = "message_sent"
    BROADCAST = "broadcast"
    PHASE_DONE = "phase_done"
    VERIFICATION_COMPLETE = "verification_complete"
    SESSION_ENDED = "session_ended"


# ---------------------------------------------------------------------------
# Data classes -- original
# ---------------------------------------------------------------------------

@dataclass
class FixAction:
    """A single text-level fix to apply to a source file."""

    finding_id: str
    file: str
    line_start: int
    line_end: int
    action: FixActionType
    old_text: str
    new_text: str
    rationale: str

    def to_dict(self) -> dict:
        return {
            "finding_id": self.finding_id,
            "file": self.file,
            "line_start": self.line_start,
            "line_end": self.line_end,
            "action": self.action.value,
            "old_text": self.old_text,
            "new_text": self.new_text,
            "rationale": self.rationale,
        }

    @classmethod
    def from_dict(cls, d: dict) -> FixAction:
        return cls(
            finding_id=d["finding_id"],
            file=d["file"],
            line_start=d["line_start"],
            line_end=d["line_end"],
            action=FixActionType(d["action"]),
            old_text=d.get("old_text", ""),
            new_text=d.get("new_text", ""),
            rationale=d.get("rationale", ""),
        )


@dataclass
class FixPlan:
    """An ordered collection of fix actions grouped by file."""

    actions: list[FixAction] = field(default_factory=list)

    def files(self) -> list[str]:
        """Return sorted list of unique files touched by this plan."""
        return sorted({a.file for a in self.actions})

    def actions_for_file(self, path: str) -> list[FixAction]:
        """Return actions for *path*, sorted by line_start descending.

        Descending order ensures earlier fixes don't shift line numbers
        for later fixes in the same file.
        """
        return sorted(
            [a for a in self.actions if a.file == path],
            key=lambda a: a.line_start,
            reverse=True,
        )

    def to_dict(self) -> dict:
        return {"actions": [a.to_dict() for a in self.actions]}

    @classmethod
    def from_dict(cls, d: dict) -> FixPlan:
        return cls(actions=[FixAction.from_dict(a) for a in d.get("actions", [])])


@dataclass
class FixResult:
    """Outcome of applying a single FixAction."""

    finding_id: str
    success: bool
    error: Optional[str] = None
    diff: str = ""

    def to_dict(self) -> dict:
        return {
            "finding_id": self.finding_id,
            "success": self.success,
            "error": self.error,
            "diff": self.diff,
        }


# ---------------------------------------------------------------------------
# Data classes -- multi-agent collaboration
# ---------------------------------------------------------------------------

@dataclass
class Reaction:
    """A reaction from an expert on a FixProposal."""

    expert: str
    reaction_type: ReactionType
    comment: str = ""
    alternative_text: str = ""  # for SUGGEST_ALTERNATIVE

    def to_dict(self) -> dict:
        return {
            "expert": self.expert,
            "reaction_type": self.reaction_type.value,
            "comment": self.comment,
            "alternative_text": self.alternative_text,
        }

    @classmethod
    def from_dict(cls, d: dict) -> Reaction:
        return cls(
            expert=d["expert"],
            reaction_type=ReactionType(d["reaction_type"]),
            comment=d.get("comment", ""),
            alternative_text=d.get("alternative_text", ""),
        )


@dataclass
class FixProposal:
    """A proposed fix awaiting consensus before application."""

    id: str = ""  # auto-generated "fp-XXXXXX"
    finding_id: str = ""
    expert_role: str = ""
    file: str = ""
    line_start: int = 0
    line_end: int = 0
    old_text: str = ""
    new_text: str = ""
    rationale: str = ""
    confidence: float = 0.8
    status: ProposalStatus = ProposalStatus.PROPOSED
    reactions: list[Reaction] = field(default_factory=list)
    related_proposal_ids: list[str] = field(default_factory=list)

    def __post_init__(self) -> None:
        if not self.id:
            self.id = "fp-" + secrets.token_hex(3)

    def to_dict(self) -> dict:
        return {
            "id": self.id,
            "finding_id": self.finding_id,
            "expert_role": self.expert_role,
            "file": self.file,
            "line_start": self.line_start,
            "line_end": self.line_end,
            "old_text": self.old_text,
            "new_text": self.new_text,
            "rationale": self.rationale,
            "confidence": self.confidence,
            "status": self.status.value,
            "reactions": [r.to_dict() for r in self.reactions],
            "related_proposal_ids": list(self.related_proposal_ids),
        }

    @classmethod
    def from_dict(cls, d: dict) -> FixProposal:
        return cls(
            id=d.get("id", ""),
            finding_id=d.get("finding_id", ""),
            expert_role=d.get("expert_role", ""),
            file=d.get("file", ""),
            line_start=d.get("line_start", 0),
            line_end=d.get("line_end", 0),
            old_text=d.get("old_text", ""),
            new_text=d.get("new_text", ""),
            rationale=d.get("rationale", ""),
            confidence=d.get("confidence", 0.8),
            status=ProposalStatus(d.get("status", "proposed")),
            reactions=[Reaction.from_dict(r) for r in d.get("reactions", [])],
            related_proposal_ids=list(d.get("related_proposal_ids", [])),
        )


@dataclass
class FindingClaim:
    """Tracks which expert has claimed a finding for fixing."""

    finding_id: str = ""
    expert_role: str = ""
    status: ClaimStatus = ClaimStatus.ACTIVE

    def to_dict(self) -> dict:
        return {
            "finding_id": self.finding_id,
            "expert_role": self.expert_role,
            "status": self.status.value,
        }

    @classmethod
    def from_dict(cls, d: dict) -> FindingClaim:
        return cls(
            finding_id=d.get("finding_id", ""),
            expert_role=d.get("expert_role", ""),
            status=ClaimStatus(d.get("status", "active")),
        )


@dataclass
class Message:
    """A message between experts in a fix session."""

    id: str = ""
    sender: str = ""
    recipient: str = ""  # or "all" for broadcast
    msg_type: MessageType = MessageType.DIRECT
    content: str = ""
    context_id: str = ""  # optional link to proposal/finding

    def __post_init__(self) -> None:
        if not self.id:
            self.id = "m-" + secrets.token_hex(4)

    def to_dict(self) -> dict:
        return {
            "id": self.id,
            "sender": self.sender,
            "recipient": self.recipient,
            "msg_type": self.msg_type.value,
            "content": self.content,
            "context_id": self.context_id,
        }

    @classmethod
    def from_dict(cls, d: dict) -> Message:
        return cls(
            id=d.get("id", ""),
            sender=d.get("sender", ""),
            recipient=d.get("recipient", ""),
            msg_type=MessageType(d.get("msg_type", "direct")),
            content=d.get("content", ""),
            context_id=d.get("context_id", ""),
        )


@dataclass
class Event:
    """An event in the fix session timeline."""

    id: str = ""
    event_type: EventType = EventType.FIX_PROPOSED
    payload: dict = field(default_factory=dict)

    def __post_init__(self) -> None:
        if not self.id:
            self.id = "e-" + secrets.token_hex(4)

    def to_dict(self) -> dict:
        return {
            "id": self.id,
            "event_type": self.event_type.value,
            "payload": dict(self.payload),
        }

    @classmethod
    def from_dict(cls, d: dict) -> Event:
        return cls(
            id=d.get("id", ""),
            event_type=EventType(d.get("event_type", "fix_proposed")),
            payload=dict(d.get("payload", {})),
        )
