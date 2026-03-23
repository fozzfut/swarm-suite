"""Append-only debate log -- JSONL with thread lock."""

import json
import logging
import secrets
import threading
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path

_log = logging.getLogger("swarm_kb.debate_store")


@dataclass
class DebateRecord:
    """A debate record capturing multi-agent deliberation."""

    id: str = ""
    created_at: str = ""
    topic: str = ""
    project_path: str = ""
    source_tool: str = ""
    source_session: str = ""
    status: str = "open"  # open|resolved|cancelled
    proposals: list[dict] = field(default_factory=list)
    winning_proposal: str = ""
    decision_id: str = ""
    participant_count: int = 0
    vote_tally: dict = field(default_factory=dict)
    tags: list[str] = field(default_factory=list)

    @staticmethod
    def generate_id() -> str:
        return "dbt-" + secrets.token_hex(4)

    def to_dict(self) -> dict:
        return {
            "id": self.id,
            "created_at": self.created_at,
            "topic": self.topic,
            "project_path": self.project_path,
            "source_tool": self.source_tool,
            "source_session": self.source_session,
            "status": self.status,
            "proposals": self.proposals,
            "winning_proposal": self.winning_proposal,
            "decision_id": self.decision_id,
            "participant_count": self.participant_count,
            "vote_tally": self.vote_tally,
            "tags": self.tags,
        }

    @classmethod
    def from_dict(cls, d: dict) -> "DebateRecord":
        return cls(
            id=d.get("id", DebateRecord.generate_id()),
            created_at=d.get("created_at", ""),
            topic=d.get("topic", ""),
            project_path=d.get("project_path", ""),
            source_tool=d.get("source_tool", ""),
            source_session=d.get("source_session", ""),
            status=d.get("status", "open"),
            proposals=d.get("proposals", []),
            winning_proposal=d.get("winning_proposal", ""),
            decision_id=d.get("decision_id", ""),
            participant_count=d.get("participant_count", 0),
            vote_tally=d.get("vote_tally", {}),
            tags=d.get("tags", []),
        )


class DebateStore:
    """Append-only debate store with in-memory query support."""

    def __init__(self, path: Path) -> None:
        self._path = Path(path)
        self._entries: list[DebateRecord] = []
        self._lock = threading.Lock()
        self._load()

    def _load(self) -> None:
        """Load existing entries from disk."""
        if not self._path.exists():
            return
        with self._lock:
            for line in self._path.read_text(encoding="utf-8").splitlines():
                line = line.strip()
                if not line:
                    continue
                try:
                    self._entries.append(DebateRecord.from_dict(json.loads(line)))
                except Exception as exc:
                    _log.warning("Skipping corrupt line in %s: %s", self._path, exc)

    def append(self, **kwargs: object) -> DebateRecord:
        """Create and persist a new debate record."""
        record = DebateRecord(
            id=DebateRecord.generate_id(),
            created_at=datetime.now(timezone.utc).isoformat(),
            **kwargs,  # type: ignore[arg-type]
        )

        with self._lock:
            self._path.parent.mkdir(parents=True, exist_ok=True)
            with open(self._path, "a", encoding="utf-8") as fh:
                fh.write(json.dumps(record.to_dict()) + "\n")
            self._entries.append(record)

        _log.info("Debate %s: %s (%s)", record.id, record.topic, record.status)
        return record

    def query(
        self,
        *,
        status: str = "",
        source_tool: str = "",
        project_path: str = "",
        tag: str = "",
    ) -> list[DebateRecord]:
        """Query debates with optional filters."""
        with self._lock:
            results = list(self._entries)

        if status:
            results = [r for r in results if r.status == status]
        if source_tool:
            results = [r for r in results if r.source_tool == source_tool]
        if project_path:
            results = [r for r in results if r.project_path == project_path]
        if tag:
            results = [r for r in results if tag in r.tags]

        return results

    def get_by_id(self, debate_id: str) -> DebateRecord | None:
        """Get a specific debate by ID."""
        with self._lock:
            for r in self._entries:
                if r.id == debate_id:
                    return r
        return None

    def count(self) -> int:
        """Count total debates."""
        with self._lock:
            return len(self._entries)
