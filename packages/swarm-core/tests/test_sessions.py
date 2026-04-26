"""Tests for SessionLifecycle template-method base."""

import json
from pathlib import Path

import pytest

from swarm_core.sessions import SessionLifecycle


class _FakeLifecycle(SessionLifecycle):
    tool_name = "test"
    session_prefix = "test"
    initial_files = ("findings.jsonl", "claims.json", "phases.json")
    array_files = ("claims.json",)


def test_create_writes_meta_and_initial_files(tmp_path: Path):
    lc = _FakeLifecycle(tmp_path)
    sid = lc.create(project_path="/some/proj", name="my-session")
    sess_dir = tmp_path / sid

    assert sess_dir.is_dir()
    meta = json.loads((sess_dir / "meta.json").read_text(encoding="utf-8"))
    assert meta["tool"] == "test"
    assert meta["project_path"] == "/some/proj"
    assert meta["name"] == "my-session"
    assert meta["status"] == "active"
    assert meta["schema_version"] == 1

    assert (sess_dir / "findings.jsonl").read_text() == ""
    assert (sess_dir / "claims.json").read_text() == "[]"
    assert (sess_dir / "phases.json").read_text() == "{}"


def test_create_session_id_format(tmp_path: Path):
    lc = _FakeLifecycle(tmp_path)
    sid = lc.create()
    parts = sid.split("-")
    assert parts[0] == "test"
    assert len(parts) == 5  # test-YYYY-MM-DD-NNN


def test_list_returns_sessions(tmp_path: Path):
    lc = _FakeLifecycle(tmp_path)
    a = lc.create()
    b = lc.create()
    out = lc.list_all()
    sids = {s["session_id"] for s in out}
    assert {a, b}.issubset(sids)


def test_end_marks_status(tmp_path: Path):
    lc = _FakeLifecycle(tmp_path)
    sid = lc.create()
    lc.end(sid)
    meta = json.loads((tmp_path / sid / "meta.json").read_text(encoding="utf-8"))
    assert meta["status"] == "completed"
    assert meta["ended_at"]


def test_get_unknown_session_raises(tmp_path: Path):
    lc = _FakeLifecycle(tmp_path)
    with pytest.raises(ValueError):
        lc.get("test-9999-99-99-001")


def test_subclass_must_set_class_attrs(tmp_path: Path):
    class _Bare(SessionLifecycle):
        pass

    with pytest.raises(TypeError):
        _Bare(tmp_path)
