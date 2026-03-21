"""Data models for ReviewSwarm -- Finding, Claim, Reaction with serialization."""

from __future__ import annotations

import secrets
from dataclasses import dataclass, field
from datetime import datetime, timezone
from enum import Enum


# ── Helper ──────────────────────────────────────────────────────────────


def now_iso() -> str:
    """Return current UTC time as ISO 8601 string."""
    return datetime.now(timezone.utc).isoformat()


# ── Enums ───────────────────────────────────────────────────────────────


class Severity(str, Enum):
    CRITICAL = "critical"
    HIGH = "high"
    MEDIUM = "medium"
    LOW = "low"
    INFO = "info"


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


class ClaimStatus(str, Enum):
    ACTIVE = "active"
    RELEASED = "released"
    EXPIRED = "expired"


class ReactionType(str, Enum):
    CONFIRM = "confirm"
    DISPUTE = "dispute"
    EXTEND = "extend"
    DUPLICATE = "duplicate"


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
            "created_at": self.created_at,
            "updated_at": self.updated_at,
        }

    @classmethod
    def from_dict(cls, d: dict) -> Finding:
        """Deserialize from a plain dict."""
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
        """Check if this claim has expired based on claimed_at + ttl_seconds."""
        claimed = datetime.fromisoformat(self.claimed_at)
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

    @staticmethod
    def generate_id() -> str:
        """Generate a reaction ID: 'r-' + 6 hex chars."""
        return "r-" + secrets.token_hex(3)

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
