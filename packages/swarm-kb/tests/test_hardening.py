"""Tests for Stage 6 Hardening session.

We test the lightweight checks (dep_hygiene, ci_presence, observability,
secrets-naive-fallback) directly. mypy / pytest-cov / pip-audit are
exercised at the integration level only -- their full subprocess paths
need an installed tool, not appropriate for a unit test.
"""

import json
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from swarm_kb.hardening_session import (
    start_hardening,
    run_check,
    get_hardening_report,
    CHECK_REGISTRY,
    _check_secrets,
    _check_dep_hygiene,
    _check_ci_presence,
    _check_observability,
)


def _make_project(tmp_path: Path) -> Path:
    proj = tmp_path / "proj"
    proj.mkdir()
    return proj


def test_start_creates_session(tmp_path: Path):
    sessions = tmp_path / "sessions"
    proj = _make_project(tmp_path)
    out = start_hardening(sessions, project_path=str(proj), min_coverage=90)
    assert out["min_coverage"] == 90
    assert "checks" in out and len(out["checks"]) == len(CHECK_REGISTRY)


def test_dep_hygiene_passes_with_pyproject(tmp_path: Path):
    proj = _make_project(tmp_path)
    (proj / "pyproject.toml").write_text("[project]\nname='x'\n", encoding="utf-8")
    r = _check_dep_hygiene(proj, {})
    assert r.passed
    assert r.installed


def test_dep_hygiene_fails_with_no_manifest(tmp_path: Path):
    proj = _make_project(tmp_path)
    r = _check_dep_hygiene(proj, {})
    assert not r.passed
    assert "no pyproject" in r.summary


def test_ci_presence_detects_github_actions(tmp_path: Path):
    proj = _make_project(tmp_path)
    wf = proj / ".github" / "workflows"
    wf.mkdir(parents=True)
    (wf / "ci.yml").write_text("name: x", encoding="utf-8")
    r = _check_ci_presence(proj, {})
    assert r.passed
    assert "workflow" in r.summary


def test_ci_presence_fails_when_absent(tmp_path: Path):
    proj = _make_project(tmp_path)
    r = _check_ci_presence(proj, {})
    assert not r.passed


def test_observability_detects_logging(tmp_path: Path):
    proj = _make_project(tmp_path)
    (proj / "x.py").write_text(
        "import logging\nlog = logging.getLogger(__name__)\n", encoding="utf-8")
    r = _check_observability(proj, {})
    assert r.passed


def test_observability_fails_without_logging(tmp_path: Path):
    proj = _make_project(tmp_path)
    (proj / "x.py").write_text("print('hi')\n", encoding="utf-8")
    r = _check_observability(proj, {})
    assert not r.passed


def test_secrets_naive_fallback_finds_aws_key(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    proj = _make_project(tmp_path)
    (proj / "config.py").write_text(
        'AWS_ACCESS_KEY_ID = "AKIAIOSFODNN7EXAMPLE"\n', encoding="utf-8")
    # Pretend gitleaks isn't installed so we hit the regex fallback
    import shutil as _shutil
    monkeypatch.setattr(_shutil, "which", lambda cmd: None if cmd == "gitleaks" else "/usr/bin/" + cmd)
    r = _check_secrets(proj, {})
    assert not r.passed
    assert r.details["findings"]
    assert r.details["findings"][0]["kind"] == "AWS access key id"


def test_run_check_persists_result(tmp_path: Path):
    sessions = tmp_path / "sessions"
    proj = _make_project(tmp_path)
    (proj / "pyproject.toml").write_text("[project]\nname='x'\n", encoding="utf-8")
    sid = start_hardening(sessions, project_path=str(proj))["session_id"]
    out = run_check(sessions, session_id=sid, check="dep_hygiene")
    assert out["passed"]
    sess_dir = sessions / sid
    assert (sess_dir / "check.dep_hygiene.json").exists()
    meta = json.loads((sess_dir / "meta.json").read_text(encoding="utf-8"))
    assert "dep_hygiene" in meta["check_results"]


def test_run_check_unknown_raises(tmp_path: Path):
    sessions = tmp_path / "sessions"
    proj = _make_project(tmp_path)
    sid = start_hardening(sessions, project_path=str(proj))["session_id"]
    with pytest.raises(ValueError):
        run_check(sessions, session_id=sid, check="bogus")


def test_get_report_aggregates(tmp_path: Path):
    sessions = tmp_path / "sessions"
    proj = _make_project(tmp_path)
    (proj / "pyproject.toml").write_text("[project]\nname='x'\n", encoding="utf-8")
    sid = start_hardening(sessions, project_path=str(proj))["session_id"]
    run_check(sessions, session_id=sid, check="dep_hygiene")
    run_check(sessions, session_id=sid, check="ci_presence")  # will fail (no CI)
    report = get_hardening_report(sessions, session_id=sid)
    assert report["blockers"] == 1
    assert "dep_hygiene" in report["report_md"]
    assert "ci_presence" in report["report_md"]
    assert "[NOT RUN]" in report["report_md"]  # unrun checks listed
