"""Session management for DocSwarm."""

from __future__ import annotations

import json
import logging
import threading
import uuid
from datetime import datetime, timezone
from pathlib import Path

from .models import DocIssue, DocPage, now_iso


def _resolve_storage_dir() -> Path:
    """Prefer ~/.swarm-kb/doc, fallback to ~/.doc-swarm."""
    swarm_kb = Path("~/.swarm-kb/doc").expanduser()
    legacy = Path("~/.doc-swarm").expanduser()
    if swarm_kb.exists():
        return swarm_kb
    if legacy.exists():
        return legacy
    return swarm_kb


_STORAGE_DIR = _resolve_storage_dir()
_log = logging.getLogger("doc_swarm.session")


class Session:
    """A documentation generation/verification session."""

    def __init__(self, session_id: str, session_dir: Path) -> None:
        self.session_id = session_id
        self._dir = session_dir
        self._pages: list[DocPage] = []
        self._issues: list[DocIssue] = []
        self._lock = threading.Lock()

    def add_page(self, page: DocPage) -> None:
        with self._lock:
            self._pages.append(page)
            self._append_page(page)
        _log.debug("Added page %s to session %s", page.path, self.session_id)

    def add_issue(self, issue: DocIssue) -> None:
        with self._lock:
            self._issues.append(issue)
            self._append_issue(issue)
        _log.debug("Added issue %s to session %s", issue.id, self.session_id)

    def _append_page(self, page: DocPage) -> None:
        """Append a single page to the JSONL file (caller holds lock)."""
        path = self._dir / "pages.jsonl"
        with open(path, "a", encoding="utf-8") as fh:
            fh.write(json.dumps(page.to_dict()) + "\n")

    def _append_issue(self, issue: DocIssue) -> None:
        """Append a single issue to the JSONL file (caller holds lock)."""
        path = self._dir / "issues.jsonl"
        with open(path, "a", encoding="utf-8") as fh:
            fh.write(json.dumps(issue.to_dict()) + "\n")

    @property
    def pages(self) -> list[DocPage]:
        with self._lock:
            return list(self._pages)

    @property
    def issues(self) -> list[DocIssue]:
        with self._lock:
            return list(self._issues)

    def write_docs(self, output_dir: Path) -> list[str]:
        """Write all generated doc pages to the output directory."""
        with self._lock:
            pages = list(self._pages)
        written = []
        output_dir.mkdir(parents=True, exist_ok=True)
        for page in pages:
            path = output_dir / page.path
            try:
                path.parent.mkdir(parents=True, exist_ok=True)
                path.write_text(page.to_markdown(), encoding="utf-8")
                written.append(str(page.path))
            except OSError as exc:
                _log.warning("Failed to write %s: %s", page.path, exc)
        return written

    def _load(self) -> None:
        """Load persisted pages and issues from JSONL files."""
        with self._lock:
            self._pages.clear()
            self._issues.clear()
            pages_path = self._dir / "pages.jsonl"
            if pages_path.exists():
                for line in pages_path.read_text(encoding="utf-8").splitlines():
                    line = line.strip()
                    if line:
                        try:
                            self._pages.append(DocPage.from_dict(json.loads(line)))
                        except (json.JSONDecodeError, KeyError, ValueError) as exc:
                            _log.warning("Skipping corrupt line in %s: %s", pages_path, exc)
            issues_path = self._dir / "issues.jsonl"
            if issues_path.exists():
                for line in issues_path.read_text(encoding="utf-8").splitlines():
                    line = line.strip()
                    if line:
                        try:
                            self._issues.append(DocIssue.from_dict(json.loads(line)))
                        except (json.JSONDecodeError, KeyError, ValueError) as exc:
                            _log.warning("Skipping corrupt line in %s: %s", issues_path, exc)

    def to_dict(self) -> dict:
        with self._lock:
            return {
                "session_id": self.session_id,
                "pages": len(self._pages),
                "issues": len(self._issues),
            }


class SessionManager:
    """Manages DocSwarm sessions."""

    def __init__(self, storage_dir: Path | None = None) -> None:
        self._storage = storage_dir or _STORAGE_DIR
        self._sessions_dir = self._storage / "sessions"
        self._sessions_dir.mkdir(parents=True, exist_ok=True)
        self._sessions: dict[str, Session] = {}
        self._lock = threading.RLock()

    def start_session(self, project_path: str, name: str | None = None) -> Session:
        with self._lock:
            today = datetime.now(timezone.utc).strftime("%Y-%m-%d")
            seq = len(list(self._sessions_dir.glob(f"doc-{today}-*"))) + 1
            session_id = f"doc-{today}-{seq:03d}"

            sess_dir = self._sessions_dir / session_id
            if sess_dir.exists():
                session_id = f"doc-{today}-{uuid.uuid4().hex[:6]}"
                sess_dir = self._sessions_dir / session_id
            sess_dir.mkdir(parents=True, exist_ok=True)

            meta = {
                "session_id": session_id,
                "project_path": project_path,
                "name": name or session_id,
                "created_at": now_iso(),
                "status": "active",
            }
            (sess_dir / "meta.json").write_text(
                json.dumps(meta, indent=2), encoding="utf-8"
            )

            session = Session(session_id, sess_dir)
            self._sessions[session_id] = session
            _log.info("Started session %s for %s", session_id, project_path)
            return session

    def get_session(self, session_id: str) -> Session:
        with self._lock:
            if session_id not in self._sessions:
                sess_dir = self._sessions_dir / session_id
                if not sess_dir.exists():
                    raise KeyError(f"Session {session_id} not found")
                session = Session(session_id, sess_dir)
                session._load()
                self._sessions[session_id] = session
            return self._sessions[session_id]
