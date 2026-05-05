"""Tests for ExpertProfiler — built-in expert loading + suggestion."""

from pathlib import Path

import pytest

from monitor_swarm.expert_profiler import ExpertProfiler


def test_list_profiles_returns_all_four_experts() -> None:
    profiler = ExpertProfiler()
    slugs = {p["slug"] for p in profiler.list_profiles()}
    expected = {
        "timing-analyst",
        "logging-instrumentation",
        "telemetry-architect",
        "trace-format-designer",
    }
    assert expected.issubset(slugs), f"missing: {expected - slugs}"


def test_each_profile_has_required_fields() -> None:
    profiler = ExpertProfiler()
    for p in profiler.list_profiles():
        assert p.get("name"), f"missing name for {p.get('slug')}"
        assert p.get("description"), f"missing description for {p.get('slug')}"
        assert p.get("system_prompt"), f"missing system_prompt for {p.get('slug')}"
        assert isinstance(p.get("uses_skills"), list)


def test_load_profile_by_slug() -> None:
    p = ExpertProfiler().load_profile("timing-analyst")
    assert p["slug"] == "timing-analyst"
    assert p["name"] == "Timing Analyst"


def test_load_unknown_slug_raises() -> None:
    with pytest.raises(FileNotFoundError):
        ExpertProfiler().load_profile("not-a-real-expert")


def test_suggest_experts_on_c_project_scores_logging_high(tmp_path: Path) -> None:
    """A logging-heavy C project should rank logging-instrumentation HIGHER
    than experts whose signals don't appear in the source — proving the
    profiler is doing relevance ranking, not just inclusion."""
    src = tmp_path / "src"
    src.mkdir()
    (src / "main.c").write_text(
        "#include <stdio.h>\n"
        "#include <SEGGER_RTT.h>\n"
        "void ADC_IRQHandler(void) {\n"
        "    printf(\"ADC isr running\\n\");\n"
        "    LOG_INFO(\"foo\");\n"
        "}\n",
        encoding="utf-8",
    )
    ranked = ExpertProfiler().suggest_experts(tmp_path)
    by_slug = {r["slug"]: r for r in ranked}
    # Absolute: logging-instrumentation matched at least one signal.
    assert by_slug["logging-instrumentation"]["score"] > 0
    # telemetry-architect should also pick up SEGGER_RTT.
    assert by_slug["telemetry-architect"]["score"] > 0
    # Relative: an unrelated expert (trace-format-designer's signals are
    # JSON / serde / structlog / etc., none of which appear in this C file)
    # MUST score lower than logging-instrumentation. This is what makes
    # `suggest_experts` actually useful as a ranking function.
    assert (
        by_slug["logging-instrumentation"]["score"]
        > by_slug["trace-format-designer"]["score"]
    )


def test_suggest_experts_on_empty_project_returns_zero_scores(tmp_path: Path) -> None:
    ranked = ExpertProfiler().suggest_experts(tmp_path)
    assert all(r["score"] == 0 for r in ranked)
