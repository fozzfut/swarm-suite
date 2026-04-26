"""Tests for TaskSimilarityStrategy -- the AgentRouter ranking implementation."""

from __future__ import annotations

from pathlib import Path

import pytest

from swarm_core.experts.registry import ExpertProfile
from swarm_core.experts.suggest import TaskSimilarityStrategy


def _make_profile(slug: str, name: str, description: str = "",
                  system_prompt: str = "", relevance_signals: dict | None = None):
    data = {"system_prompt": system_prompt}
    if relevance_signals is not None:
        data["relevance_signals"] = relevance_signals
    return ExpertProfile(
        name=name,
        description=description,
        source_file=Path(f"<{slug}>.yaml"),
        data=data,
    )


def test_ranks_higher_overlap_first():
    profiles = [
        _make_profile(
            "security",
            "Security expert",
            description="Reviews code for auth and injection vulnerabilities",
            system_prompt="Find auth bugs, injection flaws, csrf vectors",
        ),
        _make_profile(
            "perf",
            "Performance expert",
            description="Profiles slow code paths and quadratic loops",
            system_prompt="Identify n+1 queries and quadratic complexity",
        ),
    ]
    strat = TaskSimilarityStrategy()
    out = strat.suggest(profiles, "audit auth and injection in the login flow")
    assert out[0]["slug"] == "<security>"  # source_file stem -> slug
    # Verify the perf profile either ranks lower or is filtered out.
    if len(out) > 1:
        assert out[0]["confidence"] >= out[1]["confidence"]


def test_min_score_drops_irrelevant():
    profiles = [
        _make_profile("rel", "Auth", description="auth injection csrf"),
        _make_profile("irr", "Muffin", description="bake delicious muffins"),
    ]
    strat = TaskSimilarityStrategy(min_score=0.05)
    out = strat.suggest(profiles, "fix auth bug in login")
    slugs = [s["slug"] for s in out]
    assert "<rel>" in slugs
    assert "<irr>" not in slugs


def test_empty_task_returns_empty():
    profiles = [_make_profile("a", "A", description="x")]
    strat = TaskSimilarityStrategy()
    assert strat.suggest(profiles, "") == []


def test_non_string_context_raises():
    profiles = [_make_profile("a", "A")]
    strat = TaskSimilarityStrategy()
    with pytest.raises(TypeError, match="str context"):
        strat.suggest(profiles, ["not", "a", "string"])


def test_relevance_signals_included_in_match():
    profiles = [
        _make_profile(
            "p", "Plain",
            description="generic",
            relevance_signals={"keywords": ["asyncio", "concurrency"]},
        ),
    ]
    strat = TaskSimilarityStrategy()
    out = strat.suggest(profiles, "debug asyncio concurrency issue")
    assert len(out) == 1
    assert out[0]["confidence"] > 0


def test_returned_dict_shape():
    profiles = [
        _make_profile(
            "x", "Expert X",
            description="does foo bar",
            system_prompt="handles foo bar baz",
        ),
    ]
    strat = TaskSimilarityStrategy()
    out = strat.suggest(profiles, "do foo and bar")
    assert out
    item = out[0]
    assert set(item.keys()) == {"slug", "name", "description", "confidence"}
    assert isinstance(item["confidence"], float)
    assert 0.0 < item["confidence"] <= 1.0


def test_ties_broken_by_slug_ascending():
    profiles = [
        _make_profile("zebra", "Z", description="match keyword shared"),
        _make_profile("alpha", "A", description="match keyword shared"),
    ]
    strat = TaskSimilarityStrategy()
    out = strat.suggest(profiles, "match keyword shared")
    assert out[0]["confidence"] == out[1]["confidence"]
    assert out[0]["slug"] == "<alpha>"


def test_works_via_registry_suggest_path():
    """Sanity: an ExpertRegistry configured with this strategy ranks correctly."""
    from swarm_core.experts.registry import ExpertRegistry
    # Use a faux registry (no on-disk YAMLs); inject the strategy.
    reg = ExpertRegistry(
        builtin_dir=Path("/nonexistent/path/should/return/empty"),
        suggest_strategy=TaskSimilarityStrategy(),
    )
    # No profiles loaded -> empty ranking, but no crash.
    assert reg.suggest("anything") == []
