"""Template-method base for session lifecycle.

Subclass with class-level constants:
    tool_name = "review"
    session_prefix = "sess"
    initial_files = ("findings.jsonl", "claims.json", "events.jsonl")

Then call `create()`, `list_all()`, `prune(keep=10)`. Date-sequenced IDs
(`sess-2026-04-26-001`) with UUID fallback for race collisions.

Persistence is intentionally low-level: meta.json and the initial files
are seeded as empty/skeleton; the tool layer fills them in. This keeps
the lifecycle ignorant of any tool's data shape (LSP).
"""

from __future__ import annotations

import json
import shutil
import threading
import uuid
from datetime import datetime, timezone
from pathlib import Path

from ..io import atomic_write_text
from ..timeutil import now_iso
from ..logging_setup import get_logger

_log = get_logger("core.sessions")


class SessionLifecycle:
    """Per-tool session manager: create, list, prune, end.

    Override `tool_name`, `session_prefix`, and optionally `initial_files`.
    `seed_files` lets a subclass write non-empty initial content.
    """

    tool_name: str = ""
    session_prefix: str = ""
    initial_files: tuple[str, ...] = ()
    # Files that should be seeded as JSON array `[]` rather than the
    # default `{}`. Order: `array_files` overrides `initial_files` content.
    array_files: tuple[str, ...] = ()

    def __init__(self, sessions_root: Path, max_sessions: int = 100) -> None:
        if not self.tool_name or not self.session_prefix:
            raise TypeError(
                f"{type(self).__name__} must set class attributes "
                f"`tool_name` and `session_prefix`."
            )
        self._root = Path(sessions_root)
        self._max_sessions = max_sessions
        self._lock = threading.RLock()
        self._root.mkdir(parents=True, exist_ok=True)

    # ---------------------------------------------------------------- core API

    def create(self, project_path: str = "", name: str = "") -> str:
        """Create a new session directory and return its ID."""
        with self._lock:
            session_id = self._generate_id()
            sess_dir = self._root / session_id
            sess_dir.mkdir(parents=True, exist_ok=False)

            meta = self.build_meta(session_id, project_path=project_path, name=name)
            atomic_write_text(
                sess_dir / "meta.json",
                json.dumps(meta, indent=2),
            )

            for fname in self.initial_files:
                self._seed_file(sess_dir / fname)

            self.seed_files(sess_dir)
            _log.info("Session %s created in %s", session_id, sess_dir)

            self._prune_old()
            return session_id

    def end(self, session_id: str, *, status: str = "completed") -> dict:
        """Mark a session ended; returns a thin summary."""
        sess_dir = self._require_dir(session_id)
        meta_path = sess_dir / "meta.json"

        meta = self._read_meta(meta_path)
        meta["status"] = status
        meta["ended_at"] = now_iso()
        atomic_write_text(meta_path, json.dumps(meta, indent=2))

        return {"session_id": session_id, "status": status, "ended_at": meta["ended_at"]}

    def list_all(self) -> list[dict]:
        """Return one dict per session with meta + session_dir."""
        if not self._root.exists():
            return []
        out: list[dict] = []
        for entry in sorted(self._root.iterdir()):
            if not entry.is_dir():
                continue
            meta = self._read_meta(entry / "meta.json")
            meta.setdefault("session_id", entry.name)
            meta["session_dir"] = str(entry)
            out.append(meta)
        return out

    def get(self, session_id: str) -> dict:
        sess_dir = self._require_dir(session_id)
        meta = self._read_meta(sess_dir / "meta.json")
        meta.setdefault("session_id", session_id)
        meta["session_dir"] = str(sess_dir)
        return meta

    def session_dir(self, session_id: str) -> Path:
        return self._require_dir(session_id)

    # ---------------------------------------------------------------- hooks

    def build_meta(self, session_id: str, *, project_path: str, name: str) -> dict:
        """Override to extend the default meta dict."""
        return {
            "schema_version": 1,
            "tool": self.tool_name,
            "session_id": session_id,
            "name": name or session_id,
            "project_path": project_path,
            "status": "active",
            "created_at": now_iso(),
        }

    def seed_files(self, sess_dir: Path) -> None:
        """Override to write extra initial files (no-op by default)."""

    # ---------------------------------------------------------------- internals

    def _generate_id(self) -> str:
        today = datetime.now(timezone.utc).strftime("%Y-%m-%d")
        prefix = f"{self.session_prefix}-{today}"
        existing = sorted(self._root.glob(f"{prefix}-*"))
        seq = len(existing) + 1
        candidate = f"{prefix}-{seq:03d}"
        if (self._root / candidate).exists():
            candidate = f"{prefix}-{uuid.uuid4().hex[:6]}"
        return candidate

    def _seed_file(self, path: Path) -> None:
        # JSONL files start empty; .json files default to `{}` unless the
        # subclass listed them in `array_files`.
        if path.suffix == ".jsonl":
            atomic_write_text(path, "")
        elif path.suffix == ".json":
            initial = "[]" if path.name in self.array_files else "{}"
            atomic_write_text(path, initial)
        else:
            atomic_write_text(path, "")

    def _read_meta(self, meta_path: Path) -> dict:
        try:
            return json.loads(meta_path.read_text(encoding="utf-8"))
        except (FileNotFoundError, json.JSONDecodeError):
            return {}

    def _require_dir(self, session_id: str) -> Path:
        sess_dir = self._root / session_id
        if not sess_dir.is_dir():
            raise ValueError(f"Session {session_id!r} not found in {self._root}")
        return sess_dir

    def _prune_old(self) -> None:
        if self._max_sessions <= 0:
            return
        dirs = sorted(
            (d for d in self._root.iterdir() if d.is_dir()),
            key=lambda d: d.stat().st_mtime,
        )
        excess = max(0, len(dirs) - self._max_sessions)
        for d in dirs[:excess]:
            try:
                shutil.rmtree(d)
                _log.info("Pruned old session %s", d.name)
            except OSError as exc:
                _log.warning("Failed to prune %s: %s", d, exc)
