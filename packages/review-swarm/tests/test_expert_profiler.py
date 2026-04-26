# tests/test_expert_profiler.py
from pathlib import Path

import pytest

from review_swarm.expert_profiler import ExpertProfiler


class TestExpertProfiler:
    def test_list_builtin_profiles(self):
        profiler = ExpertProfiler()
        profiles = profiler.list_profiles()
        names = {p["name"] for p in profiles}
        # Updated experts (v2.0)
        assert "Concurrency Safety Expert" in names
        assert "API Contract Expert" in names
        assert "Cross-Reference Expert" in names
        # New experts (v1.0)
        assert "Error Handling Expert" in names
        assert "Resource Lifecycle Expert" in names
        assert "Dead Code Expert" in names
        assert "Security Surface Expert" in names
        assert "Dependency Drift Expert" in names
        assert "Project Context Expert" in names
        assert "Test Quality Expert" in names

    def test_load_profile(self):
        profiler = ExpertProfiler()
        profile = profiler.load_profile("threading-safety")
        assert profile["name"] == "Concurrency Safety Expert"
        assert "check_rules" in profile
        assert "system_prompt" in profile
        assert len(profile["check_rules"]) > 0

    def test_load_nonexistent_profile(self):
        profiler = ExpertProfiler()
        with pytest.raises(FileNotFoundError):
            profiler.load_profile("nonexistent-expert")

    def test_load_custom_profile(self, tmp_path):
        custom_dir = tmp_path / "custom-experts"
        custom_dir.mkdir()
        (custom_dir / "my-expert.yaml").write_text(
            'name: "My Expert"\nversion: "1.0"\ndescription: "test"\n'
            'file_patterns: ["**/*.py"]\ncheck_rules: []\nsystem_prompt: "hello"\n'
        )
        profiler = ExpertProfiler(custom_dirs=[custom_dir])
        profile = profiler.load_profile("my-expert")
        assert profile["name"] == "My Expert"

    def test_suggest_experts_threading(self, sample_project):
        profiler = ExpertProfiler()
        suggestions = profiler.suggest_experts(str(sample_project))
        names = [s["profile_name"] for s in suggestions]
        assert "threading-safety" in names

    def test_suggest_experts_docs(self, sample_project):
        profiler = ExpertProfiler()
        suggestions = profiler.suggest_experts(str(sample_project))
        names = [s["profile_name"] for s in suggestions]
        assert "api-signatures" in names
        assert "consistency" in names

    def test_suggest_returns_confidence(self, sample_project):
        profiler = ExpertProfiler()
        suggestions = profiler.suggest_experts(str(sample_project))
        for s in suggestions:
            assert "confidence" in s
            assert 0.0 <= s["confidence"] <= 1.0
