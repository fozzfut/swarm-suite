"""Session lifecycle management."""

from __future__ import annotations

import json
import shutil
import threading
import uuid
from datetime import datetime, timezone
from pathlib import Path

from .config import Config
from .event_bus import SessionEventBus
from .finding_store import FindingStore
from .claim_registry import ClaimRegistry
from .message_bus import MessageBus
from .phase_barrier import PhaseBarrier
from .reaction_engine import ReactionEngine
from .logging_config import get_logger
from .models import now_iso

_log = get_logger("session_manager")


class SessionManager:
    def __init__(self, config: Config, expert_profiler=None):
        self._config = config
        self._expert_profiler = expert_profiler
        self._stores: dict[str, FindingStore] = {}
        self._claims: dict[str, ClaimRegistry] = {}
        self._engines: dict[str, ReactionEngine] = {}
        self._event_buses: dict[str, SessionEventBus] = {}
        self._message_buses: dict[str, MessageBus] = {}
        self._phase_barriers: dict[str, PhaseBarrier] = {}
        self._lock = threading.RLock()

    def start_session(self, project_path: str, name: str | None = None) -> str:
        with self._lock:
            today = datetime.now(timezone.utc).strftime("%Y-%m-%d")
            seq = len(list(self._config.sessions_path.glob(f"sess-{today}-*"))) + 1
            session_id = f"sess-{today}-{seq:03d}"

            sess_dir = self._config.sessions_path / session_id
            if sess_dir.exists():
                # Fallback to UUID-based ID to avoid race collisions
                session_id = f"sess-{today}-{uuid.uuid4().hex[:6]}"
                sess_dir = self._config.sessions_path / session_id
            sess_dir.mkdir(parents=True, exist_ok=True)

            meta = {
                "schema_version": 1,
                "session_id": session_id,
                "project_path": project_path,
                "name": name or session_id,
                "created_at": now_iso(),
                "status": "active",
            }
            (sess_dir / "meta.json").write_text(
                json.dumps(meta, indent=2), encoding="utf-8"
            )
            (sess_dir / "findings.jsonl").write_text("", encoding="utf-8")
            (sess_dir / "claims.json").write_text("[]", encoding="utf-8")
            (sess_dir / "reactions.jsonl").write_text("", encoding="utf-8")
            (sess_dir / "events.jsonl").write_text("", encoding="utf-8")
            (sess_dir / "messages.jsonl").write_text("", encoding="utf-8")
            (sess_dir / "phases.json").write_text("{}", encoding="utf-8")

            _log.info("Session %s started for %s", session_id, project_path)

            # Auto-suggest experts if configured (spec requirement)
            if self._expert_profiler and self._config.experts.auto_suggest:
                try:
                    suggestions = self._expert_profiler.suggest_experts(project_path)
                    meta["suggested_experts"] = suggestions
                    (sess_dir / "meta.json").write_text(
                        json.dumps(meta, indent=2), encoding="utf-8"
                    )
                except Exception as exc:
                    _log.warning(
                        "Expert suggestion failed for %s: %s", project_path, exc
                    )

            # Enforce max_sessions
            self._prune_old_sessions()

            return session_id

    def end_session(self, session_id: str) -> dict:
        with self._lock:
            sess_dir = self._session_dir(session_id)

            # Read store BEFORE clearing caches
            store = self.get_finding_store(session_id)
            result = {
                "session_id": session_id,
                "status": "completed",
                "finding_count": store.count(),
                "findings_by_severity": store.count_by_severity(),
                "findings_by_status": store.count_by_status(),
            }

            # Auto-save reports (markdown + json + sarif)
            try:
                from .report_generator import ReportGenerator
                gen = ReportGenerator(store)
                (sess_dir / "report.md").write_text(
                    gen.generate(session_id, fmt="markdown"), encoding="utf-8"
                )
                (sess_dir / "report.json").write_text(
                    gen.generate(session_id, fmt="json"), encoding="utf-8"
                )
                (sess_dir / "report.sarif").write_text(
                    gen.generate_sarif(session_id), encoding="utf-8"
                )
                result["reports"] = {
                    "markdown": str(sess_dir / "report.md"),
                    "json": str(sess_dir / "report.json"),
                    "sarif": str(sess_dir / "report.sarif"),
                }
            except Exception:
                pass  # report generation is non-critical

            # Release all claims
            claims_reg = self.get_claim_registry(session_id)
            claims_reg.release_all(session_id)

            # Update meta
            meta = self._load_meta(sess_dir)
            meta["status"] = "completed"
            meta["ended_at"] = now_iso()
            if "reports" in result:
                meta["reports"] = result["reports"]
            (sess_dir / "meta.json").write_text(
                json.dumps(meta, indent=2), encoding="utf-8"
            )

            _log.info("Session %s ended: %d findings", session_id, result["finding_count"])

            # Flush any dirty findings to disk before clearing caches
            store.flush_if_dirty()

            # Clear caches after all reads are done
            self._stores.pop(session_id, None)
            self._claims.pop(session_id, None)
            self._engines.pop(session_id, None)
            self._event_buses.pop(session_id, None)
            self._message_buses.pop(session_id, None)
            self._phase_barriers.pop(session_id, None)

            return result

    def get_session(self, session_id: str) -> dict:
        sess_dir = self._session_dir(session_id)
        meta = self._load_meta(sess_dir)
        store = self.get_finding_store(session_id)
        claims = self.get_claim_registry(session_id)
        return {
            **meta,
            "finding_count": store.count(),
            "findings_by_severity": store.count_by_severity(),
            "findings_by_status": store.count_by_status(),
            "active_claims": len(claims.get_claims(session_id)),
        }

    def list_sessions(self) -> list[dict]:
        sessions: list[dict] = []
        if not self._config.sessions_path.exists():
            return sessions
        for sess_dir in sorted(self._config.sessions_path.iterdir()):
            if not sess_dir.is_dir():
                continue
            meta_file = sess_dir / "meta.json"
            if not meta_file.exists():
                continue
            meta = self._load_meta(sess_dir)
            if meta.get("status") == "corrupt":
                continue  # skip corrupt sessions
            # Auto-expire stale active sessions
            if meta.get("status") == "active":
                self._auto_expire_if_stale(sess_dir, meta)
            sessions.append(meta)
        return sessions

    def _auto_expire_if_stale(self, sess_dir: Path, meta: dict) -> None:
        """Mark session as expired if it exceeds session_timeout_hours."""
        created = meta.get("created_at", "")
        if not created:
            return
        try:
            created_dt = datetime.fromisoformat(created)
        except ValueError:
            return
        from datetime import timedelta
        timeout = timedelta(hours=self._config.session_timeout_hours)
        if datetime.now(timezone.utc) - created_dt > timeout:
            _log.info("Session %s expired (timeout)", meta.get("session_id", sess_dir.name))
            meta["status"] = "expired"
            meta["expired_at"] = now_iso()
            (sess_dir / "meta.json").write_text(
                json.dumps(meta, indent=2), encoding="utf-8"
            )

    def get_finding_store(self, session_id: str) -> FindingStore:
        with self._lock:
            if session_id not in self._stores:
                sess_dir = self._session_dir(session_id)
                self._stores[session_id] = FindingStore(
                    sess_dir / "findings.jsonl",
                    max_findings=10_000,
                )
            return self._stores[session_id]

    def get_claim_registry(self, session_id: str) -> ClaimRegistry:
        with self._lock:
            if session_id not in self._claims:
                sess_dir = self._session_dir(session_id)
                self._claims[session_id] = ClaimRegistry(sess_dir / "claims.json")
            return self._claims[session_id]

    def get_reaction_engine(self, session_id: str) -> ReactionEngine:
        with self._lock:
            if session_id not in self._engines:
                sess_dir = self._session_dir(session_id)
                store = self.get_finding_store(session_id)
                self._engines[session_id] = ReactionEngine(
                    store,
                    sess_dir / "reactions.jsonl",
                    confirm_threshold=self._config.consensus.confirm_threshold,
                )
            return self._engines[session_id]

    def get_message_bus(self, session_id: str) -> MessageBus:
        with self._lock:
            if session_id not in self._message_buses:
                sess_dir = self._session_dir(session_id)
                self._message_buses[session_id] = MessageBus(
                    session_id, sess_dir / "messages.jsonl",
                    max_messages=self._config.max_messages_per_session,
                )
            return self._message_buses[session_id]

    def get_phase_barrier(self, session_id: str) -> PhaseBarrier:
        with self._lock:
            if session_id not in self._phase_barriers:
                sess_dir = self._session_dir(session_id)
                self._phase_barriers[session_id] = PhaseBarrier(
                    session_id, sess_dir / "phases.json",
                )
            return self._phase_barriers[session_id]

    def get_event_bus(self, session_id: str) -> SessionEventBus:
        with self._lock:
            if session_id not in self._event_buses:
                sess_dir = self._session_dir(session_id)
                self._event_buses[session_id] = SessionEventBus(
                    session_id, sess_dir / "events.jsonl",
                    max_events=self._config.max_events_per_session,
                )
            return self._event_buses[session_id]

    def get_project_path(self, session_id: str) -> str:
        sess_dir = self._session_dir(session_id)
        meta = self._load_meta(sess_dir)
        return meta["project_path"]

    def _session_dir(self, session_id: str) -> Path:
        d = self._config.sessions_path / session_id
        if not d.exists():
            raise KeyError(f"Session {session_id} not found")
        return d

    def _load_meta(self, sess_dir: Path) -> dict:
        try:
            return json.loads((sess_dir / "meta.json").read_text(encoding="utf-8"))
        except (json.JSONDecodeError, OSError) as exc:
            return {"session_id": sess_dir.name, "status": "corrupt", "error": str(exc)}

    def _prune_old_sessions(self) -> None:
        """Delete oldest completed sessions if count exceeds max_sessions."""
        if not self._config.sessions_path.exists():
            return
        all_dirs = sorted(self._config.sessions_path.iterdir())
        excess = len(all_dirs) - self._config.max_sessions
        if excess <= 0:
            return
        for sess_dir in all_dirs:
            if excess <= 0:
                break
            if not sess_dir.is_dir():
                continue
            meta_file = sess_dir / "meta.json"
            if not meta_file.exists():
                continue
            meta = self._load_meta(sess_dir)
            if meta.get("status") == "corrupt":
                continue
            if meta.get("status") == "completed":
                try:
                    shutil.rmtree(sess_dir)
                except OSError:
                    continue  # skip locked/busy sessions
                sid = meta.get("session_id", sess_dir.name)
                self._stores.pop(sid, None)
                self._claims.pop(sid, None)
                self._engines.pop(sid, None)
                self._event_buses.pop(sid, None)
                self._message_buses.pop(sid, None)
                self._phase_barriers.pop(sid, None)
                excess -= 1
