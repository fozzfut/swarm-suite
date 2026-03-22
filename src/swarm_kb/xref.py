"""Cross-tool reference log -- append-only JSONL with file locking."""

from __future__ import annotations

import json
import logging
import os
import secrets
import sys
import threading
from datetime import datetime, timezone
from dataclasses import dataclass, field
from pathlib import Path

_log = logging.getLogger("swarm_kb.xref")


RELATIONS = ("fixes", "documents", "addresses", "informed_by")


@dataclass
class XRef:
    """A cross-reference between two tool sessions/entities."""

    id: str
    created_at: str
    source_tool: str
    source_session: str
    source_entity_id: str
    target_tool: str
    target_session: str
    target_entity_id: str
    relation: str
    metadata: dict = field(default_factory=dict)

    @staticmethod
    def generate_id() -> str:
        return "xr-" + secrets.token_hex(4)

    def to_dict(self) -> dict:
        return {
            "id": self.id,
            "created_at": self.created_at,
            "source_tool": self.source_tool,
            "source_session": self.source_session,
            "source_entity_id": self.source_entity_id,
            "target_tool": self.target_tool,
            "target_session": self.target_session,
            "target_entity_id": self.target_entity_id,
            "relation": self.relation,
            "metadata": self.metadata,
        }

    @classmethod
    def from_dict(cls, d: dict) -> XRef:
        return cls(
            id=d.get("id", XRef.generate_id()),
            created_at=d.get("created_at", ""),
            source_tool=d.get("source_tool", ""),
            source_session=d.get("source_session", ""),
            source_entity_id=d.get("source_entity_id", ""),
            target_tool=d.get("target_tool", ""),
            target_session=d.get("target_session", ""),
            target_entity_id=d.get("target_entity_id", ""),
            relation=d.get("relation", ""),
            metadata=d.get("metadata", {}),
        )


def _file_lock(fh, exclusive: bool = True) -> None:
    """Cross-platform file locking."""
    if sys.platform == "win32":
        import msvcrt
        msvcrt.locking(fh.fileno(), msvcrt.LK_LOCK if exclusive else msvcrt.LK_NBRLCK, 1)
    else:
        import fcntl
        fcntl.flock(fh, fcntl.LOCK_EX if exclusive else fcntl.LOCK_SH)


def _file_unlock(fh) -> None:
    """Cross-platform file unlocking."""
    if sys.platform == "win32":
        import msvcrt
        try:
            msvcrt.locking(fh.fileno(), msvcrt.LK_UNLCK, 1)
        except OSError:
            pass
    else:
        import fcntl
        fcntl.flock(fh, fcntl.LOCK_UN)


class XRefLog:
    """Append-only cross-reference log with file locking."""

    def __init__(self, xrefs_dir: Path) -> None:
        self._dir = Path(xrefs_dir)
        self._path = self._dir / "xref-index.jsonl"
        self._lock = threading.Lock()

    def append(
        self,
        source_tool: str,
        source_session: str,
        source_entity_id: str,
        target_tool: str,
        target_session: str,
        target_entity_id: str,
        relation: str,
        metadata: dict | None = None,
    ) -> XRef:
        """Create and persist a new cross-reference."""
        xref = XRef(
            id=XRef.generate_id(),
            created_at=datetime.now(timezone.utc).isoformat(),
            source_tool=source_tool,
            source_session=source_session,
            source_entity_id=source_entity_id,
            target_tool=target_tool,
            target_session=target_session,
            target_entity_id=target_entity_id,
            relation=relation,
            metadata=metadata or {},
        )

        with self._lock:
            self._dir.mkdir(parents=True, exist_ok=True)
            with open(self._path, "a", encoding="utf-8") as fh:
                fh.write(json.dumps(xref.to_dict()) + "\n")

        _log.info("XRef %s: %s/%s -> %s/%s (%s)",
                   xref.id, source_tool, source_entity_id,
                   target_tool, target_entity_id, relation)
        return xref

    def query(
        self,
        *,
        source_tool: str | None = None,
        source_session: str | None = None,
        target_tool: str | None = None,
        target_session: str | None = None,
        target_entity_id: str | None = None,
        relation: str | None = None,
    ) -> list[XRef]:
        """Query cross-references with optional filters."""
        results: list[XRef] = []

        if not self._path.exists():
            return results

        with self._lock:
            for line in self._path.read_text(encoding="utf-8").splitlines():
                line = line.strip()
                if not line:
                    continue
                try:
                    d = json.loads(line)
                    xref = XRef.from_dict(d)
                except Exception:
                    continue

                if source_tool and xref.source_tool != source_tool:
                    continue
                if source_session and xref.source_session != source_session:
                    continue
                if target_tool and xref.target_tool != target_tool:
                    continue
                if target_session and xref.target_session != target_session:
                    continue
                if target_entity_id and xref.target_entity_id != target_entity_id:
                    continue
                if relation and xref.relation != relation:
                    continue

                results.append(xref)

        return results

    def count(self) -> int:
        """Count total cross-references."""
        if not self._path.exists():
            return 0
        with self._lock:
            return sum(1 for line in self._path.read_text(encoding="utf-8").splitlines() if line.strip())
