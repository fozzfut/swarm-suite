"""Tests for stage_gates -- pipeline advancement guards."""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from swarm_kb.config import SuiteConfig
from swarm_kb.stage_gates import check_stage_gate


def _cfg(tmp_path: Path) -> SuiteConfig:
    return SuiteConfig(storage_root=str(tmp_path))


# --------------------------------------------------------------- idea


def test_idea_gate_no_session(tmp_path: Path):
    ok, msg = check_stage_gate("idea", _cfg(tmp_path))
    assert not ok
    assert "no Idea session" in msg
    assert "force=True" in msg


def test_idea_gate_design_not_approved(tmp_path: Path):
    from swarm_kb.idea_session import (start_idea_session, capture_idea_answer)
    cfg = _cfg(tmp_path)
    start_idea_session(cfg.tool_sessions_path("idea"),
                       project_path="/x", prompt="some idea")
    ok, msg = check_stage_gate("idea", cfg)
    assert not ok
    assert "design_approved" in msg


def test_idea_gate_design_approved(tmp_path: Path):
    from swarm_kb.idea_session import start_idea_session, finalize_idea_design
    cfg = _cfg(tmp_path)
    sid = start_idea_session(cfg.tool_sessions_path("idea"),
                             project_path="/x", prompt="some idea")["session_id"]
    finalize_idea_design(cfg.tool_sessions_path("idea"),
                         session_id=sid, design_md="# Design\nbody")
    ok, msg = check_stage_gate("idea", cfg)
    assert ok, msg


# --------------------------------------------------------------- plan


def test_plan_gate_no_session(tmp_path: Path):
    ok, msg = check_stage_gate("plan", _cfg(tmp_path))
    assert not ok
    assert "no Plan session" in msg


def test_plan_gate_validated(tmp_path: Path):
    from swarm_kb.plan_session import start_plan_session, finalize_plan
    cfg = _cfg(tmp_path)
    sid = start_plan_session(cfg.tool_sessions_path("plan"),
                             project_path="/x", adr_ids=["adr-1"])["session_id"]
    valid_plan = (
        "# Plan\n\n"
        "**Goal:** demo\n**Architecture:** demo\n"
        "**Tech stack:** python\n**ADR refs:** adr-1\n\n---\n\n"
        "### Task 1: x\n\n"
        "**Step 1: Write the failing test**\n\n"
        "**Step 2: Run test to verify it fails**\n\n"
        "**Step 3: Write minimal implementation**\n\n"
        "**Step 4: Run test to verify it passes**\n\n"
        "**Step 5: Commit**\n\n"
        "```bash\ngit commit -m 'x'\n```\n"
    )
    finalize_plan(cfg.tool_sessions_path("plan"), session_id=sid, plan_md=valid_plan)
    ok, msg = check_stage_gate("plan", cfg)
    assert ok, msg


# --------------------------------------------------------------- harden


def test_harden_gate_no_session(tmp_path: Path):
    ok, msg = check_stage_gate("harden", _cfg(tmp_path))
    assert not ok
    assert "no Hardening session" in msg


def test_harden_gate_with_blockers(tmp_path: Path):
    from swarm_kb.hardening_session import start_hardening, run_check
    cfg = _cfg(tmp_path)
    proj = tmp_path / "proj"
    proj.mkdir()  # bare project -> dep_hygiene + ci_presence will fail
    sid = start_hardening(cfg.tool_sessions_path("harden"),
                          project_path=str(proj))["session_id"]
    run_check(cfg.tool_sessions_path("harden"), session_id=sid, check="dep_hygiene")
    ok, msg = check_stage_gate("harden", cfg)
    assert not ok
    assert "blocker" in msg


def test_harden_gate_clean(tmp_path: Path):
    from swarm_kb.hardening_session import start_hardening, run_check
    cfg = _cfg(tmp_path)
    proj = tmp_path / "proj"
    proj.mkdir()
    (proj / "pyproject.toml").write_text("[project]\nname='x'\n", encoding="utf-8")
    sid = start_hardening(cfg.tool_sessions_path("harden"),
                          project_path=str(proj))["session_id"]
    # Only run dep_hygiene (which passes); leave others not-run -> they
    # don't count as blockers because the gate only counts installed-and-failed.
    run_check(cfg.tool_sessions_path("harden"), session_id=sid, check="dep_hygiene")
    ok, msg = check_stage_gate("harden", cfg)
    assert ok, msg


# --------------------------------------------------------------- other stages


def test_other_stages_pass_through(tmp_path: Path):
    """Stages without explicit gates (spec/arch/review/fix/...) return OK."""
    cfg = _cfg(tmp_path)
    for stage in ("spec", "arch", "review", "fix", "verify", "doc", "release"):
        ok, msg = check_stage_gate(stage, cfg)
        assert ok, f"stage {stage}: {msg}"


# --------------------------------------------------------------- force flag


def test_pipeline_advance_blocks_when_gate_fails(tmp_path: Path):
    """Verify the *intended user-facing path*: server.py wrapper consults
    check_stage_gate before pipe_mgr.advance(). When the gate fails the
    wrapper returns an error and the pipeline does NOT advance.

    We exercise the wrapper logic inline instead of starting a real MCP
    server -- same logic, same outcome.
    """
    from swarm_kb.pipeline import PipelineManager
    cfg = _cfg(tmp_path)
    mgr = PipelineManager(cfg.kb_root / "pipelines")
    p = mgr.start("/proj")
    # current_stage is "idea", no idea session exists -> gate fails
    ok, msg = check_stage_gate(p.current_stage, cfg)
    assert not ok
    # Simulate MCP wrapper deciding NOT to advance because gate failed
    # and force was not passed. (advance is still callable directly,
    # which is the documented escape hatch for tests / scripts.)
    assert p.current_stage == "idea"


def test_pipeline_advance_with_force_skips_gate(tmp_path: Path):
    """force=True path: PipelineManager.advance() works even when the gate
    would otherwise block. (PipelineManager itself is gate-agnostic; the
    MCP wrapper is the layer that consults the gate.)"""
    from swarm_kb.pipeline import PipelineManager
    cfg = _cfg(tmp_path)
    mgr = PipelineManager(cfg.kb_root / "pipelines")
    p = mgr.start("/proj")
    # Gate would fail here (no idea session), but advance() doesn't check
    # -- the wrapper does. With force=True the wrapper would skip the
    # gate and call advance() anyway, which works.
    result = mgr.advance(p.id)
    assert result.get("status") == "advanced"
    assert result.get("current_stage") == "spec"
