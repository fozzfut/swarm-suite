"""ClaimRegistry -- Advisory file claim tracking with TTL-based expiry."""

from __future__ import annotations

import json
import threading
from pathlib import Path

from .models import Claim, ClaimStatus, now_iso


class ClaimRegistry:
    """Tracks which agent is working on which file.

    Claims are soft/advisory -- they prevent duplicate work but are not
    enforced locks.  Each claim has a TTL; expired claims are filtered
    out on read.  State is persisted as a JSON array to disk.
    """

    def __init__(self, json_path: Path) -> None:
        self._path = Path(json_path)
        self._claims: list[Claim] = []
        self._lock = threading.Lock()
        self._load()

    # -- Public API -------------------------------------------------------

    def claim(
        self,
        session_id: str,
        file: str,
        expert_role: str,
        agent_id: str,
    ) -> Claim:
        """Claim a file for review.

        If an active, non-expired claim already exists for this
        *session + file + expert_role*, return the existing claim.
        Otherwise create a new claim, persist, and return it.
        Different experts can claim the same file independently.
        """
        with self._lock:
            for c in self._claims:
                if (
                    c.session_id == session_id
                    and c.file == file
                    and c.expert_role == expert_role
                    and c.status == ClaimStatus.ACTIVE
                    and not c.is_expired()
                ):
                    return c

            new_claim = Claim(
                id=Claim.generate_id(),
                session_id=session_id,
                file=file,
                expert_role=expert_role,
                agent_id=agent_id,
                claimed_at=now_iso(),
            )
            self._claims.append(new_claim)
            self._save()
            return new_claim

    def release(self, session_id: str, file: str, expert_role: str) -> None:
        """Release a claim by marking it as 'released'.

        No-op if no matching active claim is found.
        """
        with self._lock:
            for c in self._claims:
                if (
                    c.session_id == session_id
                    and c.file == file
                    and c.expert_role == expert_role
                    and c.status == ClaimStatus.ACTIVE
                ):
                    c.status = ClaimStatus.RELEASED
            self._save()

    def release_all(self, session_id: str) -> None:
        """Release all active claims for a session."""
        with self._lock:
            for c in self._claims:
                if c.session_id == session_id and c.status == ClaimStatus.ACTIVE:
                    c.status = ClaimStatus.RELEASED
            self._save()

    def get_claims(self, session_id: str) -> list[Claim]:
        """Return active, non-expired claims for a session."""
        with self._lock:
            return [
                c
                for c in self._claims
                if c.session_id == session_id
                and c.status == ClaimStatus.ACTIVE
                and not c.is_expired()
            ]

    # -- I/O --------------------------------------------------------------

    def _load(self) -> None:
        """Load claims from the JSON file into memory."""
        if not self._path.exists():
            return
        text = self._path.read_text(encoding="utf-8").strip()
        if not text:
            return
        try:
            data = json.loads(text)
            self._claims = [Claim.from_dict(d) for d in data]
        except (json.JSONDecodeError, KeyError, ValueError) as exc:
            import logging
            logging.getLogger("review_swarm.claim_registry").warning(
                "Corrupt claims file %s, starting fresh: %s", self._path, exc
            )
            self._claims = []

    def _save(self) -> None:
        """Write the full claims list to the JSON file."""
        self._path.parent.mkdir(parents=True, exist_ok=True)
        with open(self._path, "w", encoding="utf-8") as fh:
            json.dump([c.to_dict() for c in self._claims], fh, indent=2)
