"""Data models for ReviewSwarm -- Finding, Claim, Reaction with serialization.

Universal enums (Severity, ReactionType, ClaimStatus) and `now_iso` come
from `swarm_core.models` / `swarm_core.timeutil` -- single source of truth
across the suite. Tool-specific enums (Category, Action, Status) stay
local because their values are review-swarm-specific.
"""

from __future__ import annotations

import secrets
from dataclasses import dataclass, field
from enum import Enum
from typing import TypedDict

# Re-export the canonical enums + now_iso so existing
# `from .models import Severity, ...` callers keep working.
from swarm_core.models import (
    Severity,                         # noqa: F401 -- re-exported
    ReactionType,                     # noqa: F401 -- re-exported (review-swarm uses the suite-wide values)
    ClaimStatus,                      # noqa: F401 -- re-exported
    MessageType,                      # noqa: F401 -- re-exported
)
from swarm_core.timeutil import now_iso  # noqa: F401 -- re-exported


# ── Tool-specific enums (review-swarm only) ──────────────────────────────


class Category(str, Enum):
    BUG = "bug"
    OMISSION = "omission"
    INCONSISTENCY = "inconsistency"
    SECURITY = "security"
    PERFORMANCE = "performance"
    STYLE = "style"
    DESIGN = "design"


class Action(str, Enum):
    FIX = "fix"
    INVESTIGATE = "investigate"
    DOCUMENT = "document"
    IGNORE = "ignore"


class Status(str, Enum):
    OPEN = "open"
    CONFIRMED = "confirmed"
    DISPUTED = "disputed"
    FIXED = "fixed"
    WONTFIX = "wontfix"
    DUPLICATE = "duplicate"


# ── TypedDicts for structured dicts used in Finding ─────────────────────


class ReactionDict(TypedDict, total=False):
    """Expected schema for reaction dicts stored in Finding.reactions."""

    id: str
    session_id: str
    finding_id: str
    agent_id: str
    expert_role: str
    reaction: str
    reason: str
    related_finding_id: str
    created_at: str


class CommentDict(TypedDict, total=False):
    """Expected schema for comment dicts stored in Finding.comments."""

    expert_role: str
    content: str
    created_at: str


# ── Finding ─────────────────────────────────────────────────────────────


@dataclass
class Finding:
    """A code review finding reported by an expert agent."""

    # Required fields
    id: str
    session_id: str
    expert_role: str
    agent_id: str
    file: str
    line_start: int
    line_end: int

    # Optional with defaults
    snippet: str = ""
    severity: Severity = Severity.MEDIUM
    category: Category = Category.BUG
    title: str = ""
    actual: str = ""
    expected: str = ""
    source_ref: str = ""
    suggestion_action: Action = Action.INVESTIGATE
    suggestion_detail: str = ""
    confidence: float = 0.5
    tags: list[str] = field(default_factory=list)
    related_findings: list[str] = field(default_factory=list)

    # Server-managed
    status: Status = Status.OPEN
    reactions: list[dict] = field(default_factory=list)
    comments: list[dict] = field(default_factory=list)
    created_at: str = ""
    updated_at: str = ""

    @staticmethod
    def generate_id() -> str:
        """Generate a finding ID: 'f-' + 6 hex chars (8 chars total)."""
        return "f-" + secrets.token_hex(3)

    def to_dict(self) -> dict:
        """Serialize to a plain dict (enums become their string values)."""
        return {
            "id": self.id,
            "session_id": self.session_id,
            "expert_role": self.expert_role,
            "agent_id": self.agent_id,
            "file": self.file,
            "line_start": self.line_start,
            "line_end": self.line_end,
            "snippet": self.snippet,
            "severity": self.severity.value,
            "category": self.category.value,
            "title": self.title,
            "actual": self.actual,
            "expected": self.expected,
            "source_ref": self.source_ref,
            "suggestion_action": self.suggestion_action.value,
            "suggestion_detail": self.suggestion_detail,
            "confidence": self.confidence,
            "tags": list(self.tags),
            "related_findings": list(self.related_findings),
            "status": self.status.value,
            "reactions": list(self.reactions),
            "comments": list(self.comments),
            "created_at": self.created_at,
            "updated_at": self.updated_at,
        }

    @classmethod
    def from_dict(cls, d: dict) -> Finding:
        """Deserialize from a plain dict.

        Convention: d["key"] (KeyError on missing) for required fields;
        d.get("key", default) for optional fields with defaults.
        """
        return cls(
            id=d["id"],
            session_id=d["session_id"],
            expert_role=d["expert_role"],
            agent_id=d["agent_id"],
            file=d["file"],
            line_start=d["line_start"],
            line_end=d["line_end"],
            snippet=d.get("snippet", ""),
            severity=Severity(d["severity"]),
            category=Category(d["category"]),
            title=d.get("title", ""),
            actual=d.get("actual", ""),
            expected=d.get("expected", ""),
            source_ref=d.get("source_ref", ""),
            suggestion_action=Action(d["suggestion_action"]),
            suggestion_detail=d.get("suggestion_detail", ""),
            confidence=d.get("confidence", 0.5),
            tags=d.get("tags", []),
            related_findings=d.get("related_findings", []),
            status=Status(d["status"]),
            reactions=d.get("reactions", []),
            comments=d.get("comments", []),
            created_at=d.get("created_at", ""),
            updated_at=d.get("updated_at", ""),
        )


# ── Claim ───────────────────────────────────────────────────────────────


@dataclass
class Claim:
    """A file claim by an expert agent (prevents duplicate work)."""

    # Required fields
    id: str
    session_id: str
    file: str
    expert_role: str
    agent_id: str
    claimed_at: str

    # Optional with defaults
    ttl_seconds: int = 1800
    status: ClaimStatus = ClaimStatus.ACTIVE

    def is_expired(self) -> bool:
        """Check if this claim has expired based on claimed_at + ttl_seconds.

        ISO parse on every call; acceptable for < 100 claims per session.
        """
        try:
            claimed = datetime.fromisoformat(self.claimed_at)
        except (ValueError, TypeError):
            return True  # treat corrupt timestamps as expired
        now = datetime.now(timezone.utc)
        elapsed = (now - claimed).total_seconds()
        return elapsed >= self.ttl_seconds

    @staticmethod
    def generate_id() -> str:
        """Generate a claim ID: 'c-' + 6 hex chars (8 chars total)."""
        return "c-" + secrets.token_hex(3)

    def to_dict(self) -> dict:
        """Serialize to a plain dict."""
        return {
            "id": self.id,
            "session_id": self.session_id,
            "file": self.file,
            "expert_role": self.expert_role,
            "agent_id": self.agent_id,
            "claimed_at": self.claimed_at,
            "ttl_seconds": self.ttl_seconds,
            "status": self.status.value,
        }

    @classmethod
    def from_dict(cls, d: dict) -> Claim:
        """Deserialize from a plain dict."""
        return cls(
            id=d["id"],
            session_id=d["session_id"],
            file=d["file"],
            expert_role=d["expert_role"],
            agent_id=d["agent_id"],
            claimed_at=d["claimed_at"],
            ttl_seconds=d.get("ttl_seconds", 1800),
            status=ClaimStatus(d.get("status", "active")),
        )


# ── Reaction ────────────────────────────────────────────────────────────


@dataclass
class Reaction:
    """A reaction to a finding by another expert agent."""

    # Required fields
    session_id: str
    finding_id: str
    agent_id: str
    expert_role: str
    reaction: ReactionType
    reason: str

    # Optional with defaults
    related_finding_id: str = ""
    created_at: str = ""
    id: str = ""

    def __post_init__(self):
        if not self.id:
            self.id = "r-" + secrets.token_hex(3)

    def to_dict(self) -> dict:
        """Serialize to a plain dict."""
        return {
            "id": self.id,
            "session_id": self.session_id,
            "finding_id": self.finding_id,
            "agent_id": self.agent_id,
            "expert_role": self.expert_role,
            "reaction": self.reaction.value,
            "reason": self.reason,
            "related_finding_id": self.related_finding_id,
            "created_at": self.created_at,
        }

    @classmethod
    def from_dict(cls, d: dict) -> Reaction:
        """Deserialize from a plain dict."""
        return cls(
            session_id=d["session_id"],
            finding_id=d["finding_id"],
            agent_id=d["agent_id"],
            expert_role=d["expert_role"],
            reaction=ReactionType(d["reaction"]),
            reason=d["reason"],
            related_finding_id=d.get("related_finding_id", ""),
            created_at=d.get("created_at", ""),
            id=d.get("id", ""),
        )


# ── Event ──────────────────────────────────────────────────────────────


class EventType(str, Enum):
    FINDING_POSTED = "finding_posted"
    REACTION_ADDED = "reaction_added"
    STATUS_CHANGED = "status_changed"
    FILE_CLAIMED = "file_claimed"
    FILE_RELEASED = "file_released"
    SESSION_ENDED = "session_ended"
    # Agent-to-agent communication
    MESSAGE = "message"
    BROADCAST = "broadcast"


@dataclass
class Event:
    """A real-time event published when session state changes."""

    id: str
    event_type: EventType
    session_id: str
    timestamp: str
    payload: dict

    @staticmethod
    def generate_id() -> str:
        """Generate an event ID: 'e-' + 8 hex chars."""
        return "e-" + secrets.token_hex(4)

    def to_dict(self) -> dict:
        return {
            "id": self.id,
            "event_type": self.event_type.value,
            "session_id": self.session_id,
            "timestamp": self.timestamp,
            "payload": self.payload,
        }

    @classmethod
    def from_dict(cls, d: dict) -> Event:
        return cls(
            id=d["id"],
            event_type=EventType(d["event_type"]),
            session_id=d["session_id"],
            timestamp=d["timestamp"],
            payload=d["payload"],
        )


# ── Message ────────────────────────────────────────────────────────────
# MessageType is re-exported at the top of this file from swarm_core.models.


@dataclass
class Message:
    """Agent-to-agent message for active coordination."""

    id: str
    session_id: str
    from_agent: str          # expert_role of sender
    to_agent: str            # expert_role of recipient ("*" = all)
    message_type: MessageType
    content: str             # free-text message
    in_reply_to: str = ""    # message id this responds to
    urgent: bool = False     # urgent messages appear in _pending on every tool call
    # Structured context — links message to specific findings/files
    context: dict = field(default_factory=dict)
    # context example:
    #   {"finding_id": "f-a1b2c3", "file": "src/server.py",
    #    "line_start": 42, "line_end": 58, "title": "Race condition in cache"}
    created_at: str = ""

    @staticmethod
    def generate_id() -> str:
        return "m-" + secrets.token_hex(4)

    def __post_init__(self):
        if not self.id:
            self.id = Message.generate_id()
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
            "context": self.context,
            "created_at": self.created_at,
        }

    @classmethod
    def from_dict(cls, d: dict) -> Message:
        return cls(
            id=d["id"],
            session_id=d["session_id"],
            from_agent=d["from_agent"],
            to_agent=d["to_agent"],
            message_type=MessageType(d["message_type"]),
            content=d["content"],
            in_reply_to=d.get("in_reply_to", ""),
            urgent=d.get("urgent", False),
            context=d.get("context", {}),
            created_at=d.get("created_at", ""),
        )
