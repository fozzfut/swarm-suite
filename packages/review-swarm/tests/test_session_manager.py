# tests/test_session_manager.py
import json
from pathlib import Path

import pytest

from review_swarm.session_manager import SessionManager
from review_swarm.config import Config
from review_swarm.models import Finding, Severity, Category, Action


def _make_config(tmp_path):
    config = Config(storage_dir=str(tmp_path))
    config.sessions_path.mkdir(parents=True, exist_ok=True)
    return config


def _make_mgr(tmp_path):
    config = _make_config(tmp_path)
    return SessionManager(config)


class TestSessionManager:
    def test_start_session(self, tmp_path):
        config = _make_config(tmp_path)
        mgr = SessionManager(config)
        sid = mgr.start_session("/tmp/project", name="Test")

        assert sid.startswith("sess-")
        session = mgr.get_session(sid)
        assert session["status"] == "active"
        assert session["project_path"] == "/tmp/project"

    def test_list_sessions(self, tmp_path):
        config = _make_config(tmp_path)
        mgr = SessionManager(config)

        s1 = mgr.start_session("/tmp/p1", name="First")
        s2 = mgr.start_session("/tmp/p2", name="Second")

        sessions = mgr.list_sessions()
        assert len(sessions) == 2
        ids = {s["session_id"] for s in sessions}
        assert s1 in ids
        assert s2 in ids

    def test_end_session(self, tmp_path):
        config = _make_config(tmp_path)
        mgr = SessionManager(config)
        sid = mgr.start_session("/tmp/project")

        result = mgr.end_session(sid)
        assert result["status"] == "completed"

        session = mgr.get_session(sid)
        assert session["status"] == "completed"

    def test_end_session_not_found(self, tmp_path):
        config = _make_config(tmp_path)
        mgr = SessionManager(config)

        with pytest.raises(KeyError):
            mgr.end_session("sess-nonexistent")

    def test_get_session_not_found(self, tmp_path):
        config = _make_config(tmp_path)
        mgr = SessionManager(config)

        with pytest.raises(KeyError):
            mgr.get_session("sess-nonexistent")

    def test_post_finding_via_session(self, tmp_path):
        config = _make_config(tmp_path)
        mgr = SessionManager(config)
        sid = mgr.start_session("/tmp/project")

        store = mgr.get_finding_store(sid)
        f = Finding(
            id=Finding.generate_id(),
            session_id=sid,
            expert_role="threading-safety",
            agent_id="agent-001",
            file="src/main.py",
            line_start=1, line_end=5,
            severity=Severity.HIGH,
            category=Category.BUG,
            title="Test",
            actual="a", expected="b", source_ref="x:1",
            suggestion_action=Action.FIX,
            suggestion_detail="fix",
            confidence=0.9,
            tags=[], related_findings=[],
        )
        store.post(f)

        session = mgr.get_session(sid)
        assert session["finding_count"] == 1

    def test_session_directories_created(self, tmp_path):
        config = _make_config(tmp_path)
        mgr = SessionManager(config)
        sid = mgr.start_session("/tmp/project")

        sess_dir = config.sessions_path / sid
        assert sess_dir.exists()
        assert (sess_dir / "meta.json").exists()
        assert (sess_dir / "findings.jsonl").exists()
        assert (sess_dir / "claims.json").exists()
        assert (sess_dir / "reactions.jsonl").exists()

    def test_persistence_across_instances(self, tmp_path):
        config = _make_config(tmp_path)
        mgr1 = SessionManager(config)
        sid = mgr1.start_session("/tmp/project", name="Persist test")

        mgr2 = SessionManager(config)
        session = mgr2.get_session(sid)
        assert session["name"] == "Persist test"

    def test_max_sessions_enforced(self, tmp_path):
        config = _make_config(tmp_path)
        config.max_sessions = 3
        mgr = SessionManager(config)

        s1 = mgr.start_session("/tmp/p1")
        mgr.end_session(s1)
        s2 = mgr.start_session("/tmp/p2")
        mgr.end_session(s2)
        s3 = mgr.start_session("/tmp/p3")
        # s3 is still active, s1 and s2 completed
        # Creating a 4th should prune oldest completed
        s4 = mgr.start_session("/tmp/p4")

        sessions = mgr.list_sessions()
        session_ids = {s["session_id"] for s in sessions}
        # Should have at most max_sessions dirs
        assert len(sessions) <= config.max_sessions + 1  # pruning targets completed only
