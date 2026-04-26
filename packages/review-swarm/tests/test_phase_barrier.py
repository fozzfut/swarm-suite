"""Tests for PhaseBarrier -- two-pass review synchronization."""

import json

import pytest

from review_swarm.phase_barrier import PhaseBarrier


@pytest.fixture
def barrier(tmp_path):
    b = PhaseBarrier("sess-test-001", tmp_path / "phases.json")
    b.register_agent("threading-safety")
    b.register_agent("api-signatures")
    b.register_agent("consistency")
    return b


class TestPhaseBarrier:
    def test_phase_1_always_ready(self, barrier):
        result = barrier.check_phase_ready(1)
        assert result["ready"] is True

    def test_phase_2_not_ready_until_phase_1_done(self, barrier):
        result = barrier.check_phase_ready(2)
        assert result["ready"] is False
        assert set(result["waiting_for"]) == {"threading-safety", "api-signatures", "consistency"}

    def test_mark_phase_done_partial(self, barrier):
        result = barrier.mark_phase_done("threading-safety", 1)
        assert result["completed_count"] == 1
        assert result["total_agents"] == 3
        assert result["all_done"] is False
        assert "api-signatures" in result["waiting_for"]

    def test_mark_phase_done_all(self, barrier):
        barrier.mark_phase_done("threading-safety", 1)
        barrier.mark_phase_done("api-signatures", 1)
        result = barrier.mark_phase_done("consistency", 1)
        assert result["all_done"] is True
        assert result["waiting_for"] == []

    def test_phase_2_ready_after_all_phase_1(self, barrier):
        barrier.mark_phase_done("threading-safety", 1)
        barrier.mark_phase_done("api-signatures", 1)
        barrier.mark_phase_done("consistency", 1)
        result = barrier.check_phase_ready(2)
        assert result["ready"] is True

    def test_phase_2_not_ready_with_partial_phase_1(self, barrier):
        barrier.mark_phase_done("threading-safety", 1)
        barrier.mark_phase_done("api-signatures", 1)
        # consistency hasn't finished phase 1
        result = barrier.check_phase_ready(2)
        assert result["ready"] is False
        assert "consistency" in result["waiting_for"]

    def test_full_two_pass_workflow(self, barrier):
        # Phase 1: all review
        for agent in ["threading-safety", "api-signatures", "consistency"]:
            barrier.mark_phase_done(agent, 1)

        assert barrier.check_phase_ready(2)["ready"] is True

        # Phase 2: all cross-check
        for agent in ["threading-safety", "api-signatures", "consistency"]:
            barrier.mark_phase_done(agent, 2)

        assert barrier.check_phase_ready(3)["ready"] is True

    def test_get_status(self, barrier):
        barrier.mark_phase_done("threading-safety", 1)
        barrier.mark_phase_done("api-signatures", 1)

        status = barrier.get_status()
        assert "threading-safety" in status["registered_agents"]
        assert len(status["phases"][1]["completed"]) == 2
        assert "consistency" in status["phases"][1]["waiting_for"]

    def test_unregistered_agent_auto_registers(self, barrier):
        barrier.mark_phase_done("security-surface", 1)
        assert "security-surface" in barrier.registered_agents()


class TestPhaseBarrierPersistence:
    def test_persists_to_disk(self, barrier, tmp_path):
        barrier.mark_phase_done("threading-safety", 1)
        phases_file = tmp_path / "phases.json"
        assert phases_file.exists()
        data = json.loads(phases_file.read_text())
        assert "threading-safety" in data["agents"]

    def test_loads_from_disk(self, tmp_path):
        phases_file = tmp_path / "phases.json"
        data = {
            "agents": ["a", "b"],
            "phases": {"1": {"a": "2026-03-22T10:00:00Z"}},
        }
        phases_file.write_text(json.dumps(data))

        b = PhaseBarrier("sess-test", phases_file)
        assert "a" in b.registered_agents()
        result = b.check_phase_ready(2)
        assert result["ready"] is False
        assert "b" in result["waiting_for"]

    def test_corrupt_file_handled(self, tmp_path):
        phases_file = tmp_path / "phases.json"
        phases_file.write_text("not valid json{{{")
        b = PhaseBarrier("sess-test", phases_file)
        assert b.registered_agents() == set()
