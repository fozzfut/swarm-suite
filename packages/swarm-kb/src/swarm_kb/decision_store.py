"""Append-only decision log (ADR store) -- JSONL with thread lock."""

import copy
import json
import logging
import os
import secrets
import tempfile
import threading
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path

_log = logging.getLogger("swarm_kb.decision_store")


@dataclass
class Decision:
    """An architectural decision record."""

    id: str = ""
    created_at: str = ""
    title: str = ""
    status: str = "proposed"  # proposed|accepted|rejected|superseded
    rationale: str = ""
    context: str = ""
    consequences: list[str] = field(default_factory=list)
    source_tool: str = ""  # arch|review|fix|manual
    source_session: str = ""
    debate_id: str = ""
    project_path: str = ""
    tags: list[str] = field(default_factory=list)
    superseded_by: str = ""

    @staticmethod
    def generate_id() -> str:
        return "adr-" + secrets.token_hex(4)

    def to_dict(self) -> dict:
        return {
            "id": self.id,
            "created_at": self.created_at,
            "title": self.title,
            "status": self.status,
            "rationale": self.rationale,
            "context": self.context,
            "consequences": self.consequences,
            "source_tool": self.source_tool,
            "source_session": self.source_session,
            "debate_id": self.debate_id,
            "project_path": self.project_path,
            "tags": self.tags,
            "superseded_by": self.superseded_by,
        }

    @classmethod
    def from_dict(cls, d: dict) -> "Decision":
        return cls(
            id=d.get("id", Decision.generate_id()),
            created_at=d.get("created_at", ""),
            title=d.get("title", ""),
            status=d.get("status", "proposed"),
            rationale=d.get("rationale", ""),
            context=d.get("context", ""),
            consequences=list(d.get("consequences", [])),
            source_tool=d.get("source_tool", ""),
            source_session=d.get("source_session", ""),
            debate_id=d.get("debate_id", ""),
            project_path=d.get("project_path", ""),
            tags=list(d.get("tags", [])),
            superseded_by=d.get("superseded_by", ""),
        )


class DecisionStore:
    """Append-only decision store with in-memory query support."""

    def __init__(self, path: Path) -> None:
        self._path = Path(path)
        self._entries: list[Decision] = []
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
                    self._entries.append(Decision.from_dict(json.loads(line)))
                except Exception as exc:
                    _log.warning("Skipping corrupt line in %s: %s", self._path, exc)

    def _atomic_write(self) -> None:
        """Rewrite the JSONL file atomically via tempfile + os.replace."""
        self._path.parent.mkdir(parents=True, exist_ok=True)
        content = "\n".join(json.dumps(d.to_dict()) for d in self._entries) + "\n"
        tmp_fd, tmp_path = tempfile.mkstemp(dir=str(self._path.parent), suffix=".tmp")
        try:
            fh = os.fdopen(tmp_fd, "w", encoding="utf-8")
            with fh:
                fh.write(content)
            os.replace(tmp_path, str(self._path))
        except Exception:
            try:
                os.close(tmp_fd)
            except OSError:
                pass
            try:
                os.unlink(tmp_path)
            except OSError:
                pass
            raise

    def append(
        self,
        *,
        title: str = "",
        status: str = "proposed",
        rationale: str = "",
        context: str = "",
        consequences: list[str] | None = None,
        source_tool: str = "",
        source_session: str = "",
        debate_id: str = "",
        project_path: str = "",
        tags: list[str] | None = None,
    ) -> Decision:
        """Create and persist a new decision."""
        decision = Decision(
            id=Decision.generate_id(),
            created_at=datetime.now(timezone.utc).isoformat(),
            title=title,
            status=status,
            rationale=rationale,
            context=context,
            consequences=list(consequences) if consequences else [],
            source_tool=source_tool,
            source_session=source_session,
            debate_id=debate_id,
            project_path=project_path,
            tags=list(tags) if tags else [],
        )

        with self._lock:
            self._entries.append(decision)
            self._atomic_write()

        _log.info("Decision %s: %s (%s)", decision.id, decision.title, decision.status)
        return decision

    def query(
        self,
        *,
        status: str = "",
        source_tool: str = "",
        tag: str = "",
        project_path: str = "",
    ) -> list[Decision]:
        """Query decisions with optional filters."""
        with self._lock:
            results = list(self._entries)
            if status:
                results = [d for d in results if d.status == status]
            if source_tool:
                results = [d for d in results if d.source_tool == source_tool]
            if tag:
                results = [d for d in results if tag in d.tags]
            if project_path:
                results = [d for d in results if d.project_path == project_path]
            return [copy.deepcopy(d) for d in results]

    def get_by_id(self, decision_id: str) -> Decision | None:
        """Get a specific decision by ID."""
        with self._lock:
            for d in self._entries:
                if d.id == decision_id:
                    return copy.deepcopy(d)
        return None

    def update_status(
        self, decision_id: str, new_status: str, superseded_by: str = ""
    ) -> bool:
        """Update a decision's status. Rewrites the JSONL file atomically."""
        with self._lock:
            found = False
            for d in self._entries:
                if d.id == decision_id:
                    d.status = new_status
                    if superseded_by:
                        d.superseded_by = superseded_by
                    found = True
                    break

            if not found:
                return False

            # Rewrite file with updated entries atomically
            self._atomic_write()

        _log.info("Decision %s status -> %s", decision_id, new_status)
        return True

    def count(self) -> int:
        """Count total decisions."""
        with self._lock:
            return len(self._entries)
