import json
import os
import tempfile
from pathlib import Path

import pytest


@pytest.fixture
def tmp_storage(tmp_path):
    """Temporary storage directory mimicking ~/.review-swarm/."""
    sessions_dir = tmp_path / "sessions"
    sessions_dir.mkdir()
    experts_dir = tmp_path / "experts"
    experts_dir.mkdir()
    custom_dir = tmp_path / "custom-experts"
    custom_dir.mkdir()
    return tmp_path


@pytest.fixture
def sample_session_dir(tmp_storage):
    """Create a session directory with empty files."""
    sess_dir = tmp_storage / "sessions" / "sess-test-001"
    sess_dir.mkdir()
    meta = {
        "schema_version": 1,
        "session_id": "sess-test-001",
        "project_path": "/tmp/test-project",
        "name": "Test Session",
        "created_at": "2026-03-21T10:00:00Z",
        "status": "active",
    }
    (sess_dir / "meta.json").write_text(json.dumps(meta))
    (sess_dir / "findings.jsonl").write_text("")
    (sess_dir / "claims.json").write_text("[]")
    (sess_dir / "reactions.jsonl").write_text("")
    (sess_dir / "events.jsonl").write_text("")
    (sess_dir / "messages.jsonl").write_text("")
    return sess_dir


@pytest.fixture
def sample_project(tmp_path):
    """Create a minimal Python project for expert profiler tests."""
    proj = tmp_path / "sample-project"
    proj.mkdir()
    (proj / "main.py").write_text(
        "import threading\nfrom concurrent.futures import ThreadPoolExecutor\n"
    )
    (proj / "utils.py").write_text("def helper():\n    pass\n")
    tests_dir = proj / "tests"
    tests_dir.mkdir()
    (tests_dir / "test_main.py").write_text("def test_main():\n    pass\n")
    docs_dir = proj / "docs"
    docs_dir.mkdir()
    (docs_dir / "readme.md").write_text("# Sample\n")
    return proj
