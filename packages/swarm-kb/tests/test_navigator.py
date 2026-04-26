"""Tests for kb_navigator_state -- the snapshot driving the navigator skill."""

from __future__ import annotations

from pathlib import Path

import pytest

from swarm_kb.judging import JudgingEngine
from swarm_kb.navigator import navigator_state
from swarm_kb.pgve import PgveStore
from swarm_kb.pipeline import PipelineManager
from swarm_kb.verification import VerificationStore


@pytest.fixture
def project(tmp_path):
    p = tmp_path / "proj"
    p.mkdir()
    return str(p)


# ---------------------------------------------------------------------------
# No pipeline -> "start one" suggestion
# ---------------------------------------------------------------------------


def test_no_pipeline_suggests_start(project, tmp_path):
    pm = PipelineManager(tmp_path / "pipelines")
    snap = navigator_state(project, pipeline_manager=pm)
    assert snap["active_pipeline"] is None
    suggestions = snap["suggested_next_steps"]
    assert any(s["kind"] == "start" for s in suggestions)
    start = next(s for s in suggestions if s["kind"] == "start")
    assert "kb_start_pipeline" in start["tools"]
    assert start.get("needs_clarification")  # navigator should ask greenfield/embedded


# ---------------------------------------------------------------------------
# Active pipeline -> stage-default suggestion + advance option
# ---------------------------------------------------------------------------


def test_active_pipeline_suggests_stage_default_and_advance(project, tmp_path):
    pm = PipelineManager(tmp_path / "pipelines")
    pipe = pm.start(project)
    pm.skip_to(pipe.id, "arch")     # go to arch (a non-optional stage)
    snap = navigator_state(project, pipeline_manager=pm)
    pipe_view = snap["active_pipeline"]
    assert pipe_view is not None
    assert pipe_view["current_stage"] == "arch"

    suggestions = snap["suggested_next_steps"]
    kinds = {s["kind"] for s in suggestions}
    assert "stage_continue" in kinds
    assert "advance" in kinds


# ---------------------------------------------------------------------------
# Open artifacts -> "continue this artifact" suggestions
# ---------------------------------------------------------------------------


def test_open_pgve_session_yields_continue_suggestion(project, tmp_path):
    pm = PipelineManager(tmp_path / "pipelines")
    pm.start(project)
    pgve = PgveStore(tmp_path / "pgve")
    s = pgve.start(task_spec="implement file lock", project_path=project,
                   max_candidates=3)

    snap = navigator_state(project, pipeline_manager=pm, pgve_store=pgve)
    artifacts = snap["active_artifacts"]
    assert len(artifacts["pgve"]) == 1
    assert artifacts["pgve"][0]["id"] == s.id

    continue_pgve = [
        x for x in snap["suggested_next_steps"] if x["kind"] == "continue_artifact"
    ]
    assert continue_pgve, "open pgve must yield a continue_artifact suggestion"
    assert any("PGVE" in x["label"] for x in continue_pgve)


def test_partially_judged_judging_yields_continue_suggestion(project, tmp_path):
    pm = PipelineManager(tmp_path / "pipelines")
    pm.start(project)
    judg = JudgingEngine(tmp_path / "judg")
    j = judg.start("evaluate fp-x", dimensions=["correctness", "regression"],
                   project_path=project)
    judg.judge(j.id, judge="security", dimension="correctness",
               verdict="pass", rationale="ok")
    # 1/2 dimensions covered -> open continue suggestion expected.

    snap = navigator_state(project, pipeline_manager=pm, judging_engine=judg)
    suggs = [s for s in snap["suggested_next_steps"]
             if s["kind"] == "continue_artifact"]
    assert any("judging" in s["label"].lower() for s in suggs)


def test_open_verification_yields_continue_suggestion(project, tmp_path):
    pm = PipelineManager(tmp_path / "pipelines")
    pm.start(project)
    verify = VerificationStore(tmp_path / "verify")
    r = verify.start(fix_session="fix-x", project_path=project)
    verify.add_evidence(r.id, kind="manual_note", summary="initial")

    snap = navigator_state(project, pipeline_manager=pm,
                           verification_store=verify)
    suggs = snap["suggested_next_steps"]
    assert any(s["kind"] == "continue_artifact" and "verification" in s["label"].lower()
               for s in suggs)


# ---------------------------------------------------------------------------
# Stage info echoed for the current stage
# ---------------------------------------------------------------------------


def test_current_stage_info_includes_actions(project, tmp_path):
    pm = PipelineManager(tmp_path / "pipelines")
    pipe = pm.start(project)
    pm.skip_to(pipe.id, "arch")     # arch is the canonical "required" stage
    snap = navigator_state(project, pipeline_manager=pm)
    info = snap["current_stage_info"]
    assert info["name"]
    assert info["actions"]              # STAGE_INFO['arch']['actions'] is non-empty
    assert info["optional"] is False    # arch is required


def test_doc_stage_marked_optional(project, tmp_path):
    pm = PipelineManager(tmp_path / "pipelines")
    pipe = pm.start(project)
    # Skip directly to doc to inspect its stage info.
    pm.skip_to(pipe.id, "doc")

    snap = navigator_state(project, pipeline_manager=pm)
    info = snap["current_stage_info"]
    assert info["optional"] is True
    # And among suggestions there should be a "skip" option.
    skip = [s for s in snap["suggested_next_steps"] if s["kind"] == "skip"]
    assert skip, "doc stage must offer an explicit skip option (it's optional)"
    assert "kb_skip_stage" in skip[0]["tools"]


# ---------------------------------------------------------------------------
# Suggestion cap
# ---------------------------------------------------------------------------


def test_suggestions_capped_to_keep_navigator_concise(project, tmp_path):
    """Even with many open artifacts, suggestions are capped at ~4 to keep
    the navigator's offer to the user short."""
    pm = PipelineManager(tmp_path / "pipelines")
    pm.start(project)
    pgve = PgveStore(tmp_path / "pgve")
    judg = JudgingEngine(tmp_path / "judg")
    verify = VerificationStore(tmp_path / "verify")

    # Create a bunch of open artifacts.
    for i in range(5):
        pgve.start(task_spec=f"task-{i}", project_path=project)
        verify.start(fix_session=f"fix-{i}", project_path=project)
        j = judg.start(f"subject-{i}", dimensions=["a", "b"], project_path=project)

    snap = navigator_state(project, pipeline_manager=pm,
                           pgve_store=pgve, judging_engine=judg,
                           verification_store=verify)
    assert len(snap["suggested_next_steps"]) <= 4


# ---------------------------------------------------------------------------
# Defensive: missing engines just yield empty artifacts
# ---------------------------------------------------------------------------


def test_missing_engines_dont_break_snapshot(project):
    snap = navigator_state(project)
    # No engines passed -> empty everywhere, but we still get a "start"
    # suggestion since pipeline is also missing.
    assert snap["active_pipeline"] is None
    assert snap["active_artifacts"] == {
        "judgings": [], "verifications": [], "pgve": [],
        "flows": [], "debates": [],
    }
    assert snap["recent_decisions"] == []
    assert snap["suggested_next_steps"]   # at least the start-pipeline option
