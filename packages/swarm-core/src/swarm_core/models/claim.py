"""Claim model -- prevents two agents working the same target concurrently."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
from enum import Enum

from ..ids import generate_id
from ..timeutil import now_iso


class ClaimStatus(str, Enum):
    ACTIVE = "active"
    RELEASED = "released"
    EXPIRED = "expired"


@dataclass
class Claim:
    """A claim that an expert is working on a target (file, finding, etc.).

    `target_id` is the thing being claimed -- a file path, a finding ID,
    a proposal ID. `ttl_seconds` defaults to 30 minutes; expired claims
    can be reaped by the holder of the registry.
    """

    session_id: str
    target_id: str
    expert_role: str
    ttl_seconds: int = 1800
    status: ClaimStatus = ClaimStatus.ACTIVE
    id: str = ""
    claimed_at: str = ""

    def __post_init__(self) -> None:
        if not self.id:
            self.id = generate_id("c")
        if not self.claimed_at:
            self.claimed_at = now_iso()

    def is_expired(self) -> bool:
        """ISO-parse claimed_at and compare against TTL.

        Treats a corrupt timestamp as expired so a bad record doesn't
        permanently lock a target.
        """
        try:
            claimed = datetime.fromisoformat(self.claimed_at)
        except (ValueError, TypeError):
            return True
        elapsed = (datetime.now(timezone.utc) - claimed).total_seconds()
        return elapsed >= self.ttl_seconds

    def to_dict(self) -> dict:
        return {
            "id": self.id,
            "session_id": self.session_id,
            "target_id": self.target_id,
            "expert_role": self.expert_role,
            "ttl_seconds": self.ttl_seconds,
            "status": self.status.value,
            "claimed_at": self.claimed_at,
        }

    @classmethod
    def from_dict(cls, d: dict) -> "Claim":
        return cls(
            id=d.get("id", ""),
            session_id=d["session_id"],
            target_id=d["target_id"],
            expert_role=d["expert_role"],
            ttl_seconds=d.get("ttl_seconds", 1800),
            status=ClaimStatus(d.get("status", "active")),
            claimed_at=d.get("claimed_at", ""),
        )
