"""Tests for Stage 7 Release session.

We test the pure logic (version bump heuristic, pyproject validation,
changelog grouping). Subprocess paths (git log, python -m build) need
real environments and are exercised at integration level only.
"""

import json
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from swarm_kb.release_session import (
    start_release,
    validate_pyproject,
    release_summary,
    _bump,
    _strip_conv,
)


def test_bump_patch():
    assert _bump("1.2.3", "patch") == "1.2.4"


def test_bump_minor_resets_patch():
    assert _bump("1.2.3", "minor") == "1.3.0"


def test_bump_major_resets_minor_and_patch():
    assert _bump("1.2.3", "major") == "2.0.0"


def test_bump_unknown_kind_falls_back_to_patch():
    # Defensive default: if `propose_version_bump` ever emits an unrecognized
    # kind we still increment the lowest version part rather than no-op.
    assert _bump("1.2.3", "wat") == "1.2.4"


def test_bump_non_semver_keeps_version():
    assert _bump("0.1", "minor") == "0.1"


def test_strip_conv_removes_prefix():
    assert _strip_conv("feat: add auth") == "add auth"
    assert _strip_conv("fix!: break X") == "break X"
    assert _strip_conv("docs: update README") == "update README"


def test_validate_pyproject_passes_with_minimum_fields(tmp_path: Path):
    proj = tmp_path / "proj"
    proj.mkdir()
    (proj / "pyproject.toml").write_text(
        '[project]\n'
        'name = "demo"\n'
        'version = "0.1.0"\n'
        'description = "demo"\n'
        'license = {text = "MIT"}\n'
        'authors = [{name = "x"}]\n'
        'readme = "README.md"\n'
        'requires-python = ">=3.10"\n',
        encoding="utf-8",
    )
    (proj / "LICENSE").write_text("MIT", encoding="utf-8")

    sessions = tmp_path / "s"
    sid = start_release(sessions, project_path=str(proj))["session_id"]
    out = validate_pyproject(sessions, session_id=sid)
    assert out["valid"], out["errors"]


def test_validate_pyproject_catches_missing_fields(tmp_path: Path):
    proj = tmp_path / "proj"
    proj.mkdir()
    (proj / "pyproject.toml").write_text(
        '[project]\nname = "demo"\nversion = "0.1.0"\n',
        encoding="utf-8",
    )
    sessions = tmp_path / "s"
    sid = start_release(sessions, project_path=str(proj))["session_id"]
    out = validate_pyproject(sessions, session_id=sid)
    assert not out["valid"]
    assert any("description" in e for e in out["errors"])
    assert any("LICENSE file" in e for e in out["errors"])


def test_release_summary_not_ready_when_subtasks_skipped(tmp_path: Path):
    proj = tmp_path / "proj"
    proj.mkdir()
    sessions = tmp_path / "s"
    sid = start_release(sessions, project_path=str(proj))["session_id"]
    out = release_summary(sessions, session_id=sid)
    assert not out["ready"]
    assert "twine upload" not in out["next_action"]
