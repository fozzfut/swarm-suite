"""Claim registry -- atomic check+insert prevents two agents working the same target.

Avoids the TOCTOU bug where two agents both see "not claimed" and both
acquire. `try_claim` is the only atomic API; never compose `is_claimed`
+ `claim` from outside.
"""

from __future__ import annotations

import threading

from ..models.claim import Claim, ClaimStatus
from ..logging_setup import get_logger

_log = get_logger("core.claim_registry")


class ClaimRegistry:
    """In-memory map of target_id -> active Claim.

    Persistence is the caller's responsibility; the registry only owns
    the atomic semantics. Reload at startup by calling `restore` with
    persisted claim dicts.
    """

    def __init__(self) -> None:
        self._claims: dict[str, Claim] = {}
        self._lock = threading.RLock()

    def try_claim(
        self,
        session_id: str,
        target_id: str,
        expert_role: str,
        ttl_seconds: int = 1800,
    ) -> Claim | None:
        """Atomically claim `target_id`. Returns Claim on success, None if already held."""
        with self._lock:
            existing = self._claims.get(target_id)
            if existing and existing.status == ClaimStatus.ACTIVE and not existing.is_expired():
                return None
            claim = Claim(
                session_id=session_id,
                target_id=target_id,
                expert_role=expert_role,
                ttl_seconds=ttl_seconds,
            )
            self._claims[target_id] = claim
            _log.info("Target %s claimed by %s", target_id, expert_role)
            return claim

    def release(self, target_id: str, expert_role: str) -> bool:
        """Release a claim. Returns True if a matching active claim was released."""
        with self._lock:
            existing = self._claims.get(target_id)
            if not existing or existing.expert_role != expert_role:
                return False
            existing.status = ClaimStatus.RELEASED
            return True

    def reap_expired(self) -> list[str]:
        """Mark all expired claims as EXPIRED. Returns released target_ids."""
        released: list[str] = []
        with self._lock:
            for tid, c in self._claims.items():
                if c.status == ClaimStatus.ACTIVE and c.is_expired():
                    c.status = ClaimStatus.EXPIRED
                    released.append(tid)
        return released

    def get(self, target_id: str) -> Claim | None:
        with self._lock:
            return self._claims.get(target_id)

    def active_claims(self) -> list[Claim]:
        with self._lock:
            return [c for c in self._claims.values() if c.status == ClaimStatus.ACTIVE]

    def restore(self, dicts: list[dict]) -> None:
        with self._lock:
            for d in dicts:
                claim = Claim.from_dict(d)
                self._claims[claim.target_id] = claim
