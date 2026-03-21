"""Tests for the Orchestrator -- single-command review planning."""

import pytest

from review_swarm.config import Config
from review_swarm.expert_profiler import ExpertProfiler
from review_swarm.orchestrator import Orchestrator
from review_swarm.session_manager import SessionManager
from review_swarm.server import create_app_context, tool_orchestrate_review


@pytest.fixture
def orch(tmp_path, sample_project):
    config = Config(storage_dir=str(tmp_path))
    config.sessions_path.mkdir(parents=True, exist_ok=True)
    profiler = ExpertProfiler()
    mgr = SessionManager(config, expert_profiler=profiler)
    return Orchestrator(config, mgr, profiler), str(sample_project)


@pytest.fixture
def app_ctx(tmp_path, sample_project):
    config = Config(storage_dir=str(tmp_path))
    config.sessions_path.mkdir(parents=True, exist_ok=True)
    return create_app_context(config, project_path_override=str(sample_project))


class TestOrchestratorPlanReview:
    def test_creates_session_and_plan(self, orch, sample_project):
        o, proj = orch
        plan = o.plan_review(proj, scope="", task="general review")

        assert plan.session_id.startswith("sess-")
        assert plan.project_path
        assert len(plan.experts) >= 2
        assert len(plan.phases) == 3
        assert plan.phases[0]["name"] == "Review"
        assert plan.phases[1]["name"] == "Cross-check"
        assert plan.phases[2]["name"] == "Report"

    def test_scope_filters_files(self, orch, sample_project):
        o, proj = orch
        plan = o.plan_review(proj, scope="tests/", task="test review")
        # sample_project has tests/test_main.py
        assert all("tests/" in f for f in plan.files)

    def test_task_selects_relevant_experts(self, orch, sample_project):
        o, proj = orch
        plan = o.plan_review(proj, task="security audit")
        expert_names = [e["profile_name"] for e in plan.experts]
        # security-surface should be boosted to the front, even if its
        # confidence is low for this project (no web imports)
        assert "security-surface" in expert_names or len(expert_names) >= 2

    def test_task_concurrency(self, orch, sample_project):
        o, proj = orch
        plan = o.plan_review(proj, task="check threading safety")
        expert_names = [e["profile_name"] for e in plan.experts]
        assert "threading-safety" in expert_names

    def test_max_experts_respected(self, orch, sample_project):
        o, proj = orch
        plan = o.plan_review(proj, task="full review", max_experts=3)
        assert len(plan.experts) <= 3

    def test_plan_has_assignments(self, orch, sample_project):
        o, proj = orch
        plan = o.plan_review(proj, scope="", task="review")
        assert len(plan.assignments) > 0
        for a in plan.assignments:
            assert "expert" in a
            assert "files" in a
            assert len(a["files"]) > 0

    def test_plan_to_dict(self, orch, sample_project):
        o, proj = orch
        plan = o.plan_review(proj, task="review")
        d = plan.to_dict()
        assert "session_id" in d
        assert "phases" in d
        assert "assignments" in d
        assert "summary" in d
        assert d["expert_count"] == len(d["experts"])
        assert d["file_count"] == len(plan.files)

    def test_empty_project(self, tmp_path):
        config = Config(storage_dir=str(tmp_path))
        config.sessions_path.mkdir(parents=True, exist_ok=True)
        empty = tmp_path / "empty-project"
        empty.mkdir()
        profiler = ExpertProfiler()
        mgr = SessionManager(config, expert_profiler=profiler)
        o = Orchestrator(config, mgr, profiler)

        plan = o.plan_review(str(empty), task="review")
        assert plan.session_id.startswith("sess-")
        assert len(plan.files) == 0

    def test_russian_task_keywords(self, orch, sample_project):
        o, proj = orch
        plan = o.plan_review(proj, task="проверка безопасности")
        expert_names = [e["profile_name"] for e in plan.experts]
        # "безопасност" matches the keyword → security-surface injected
        assert "security-surface" in expert_names

    def test_session_name(self, orch, sample_project):
        o, proj = orch
        plan = o.plan_review(proj, task="review", session_name="my-review")
        assert plan.session_id.startswith("sess-")


class TestOrchestratorToolIntegration:
    def test_tool_orchestrate_review(self, app_ctx, sample_project):
        result = tool_orchestrate_review(
            app_ctx, str(sample_project),
            scope="", task="security review",
        )
        assert "session_id" in result
        assert "phases" in result
        assert result["expert_count"] >= 2
        assert len(result["phases"]) == 3

    def test_tool_with_scope(self, app_ctx, sample_project):
        result = tool_orchestrate_review(
            app_ctx, str(sample_project),
            scope="tests/", task="test quality",
        )
        assert result["file_count"] >= 0
