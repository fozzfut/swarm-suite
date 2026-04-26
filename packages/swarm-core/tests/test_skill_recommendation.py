"""Tests for task-conditioned skill recommendation + filtered composition."""

from __future__ import annotations

from pathlib import Path

import pytest

from swarm_core.experts.registry import ExpertProfile
from swarm_core.skills.registry import (
    Skill,
    SkillRegistry,
    _tokenise,
)


# ---------- _tokenise ----------------------------------------------------------


def test_tokenise_strips_short_and_stopwords():
    tokens = _tokenise("Use this when debugging the asyncio loop")
    assert "use" not in tokens          # 3 chars but stopword
    assert "the" not in tokens
    assert "debugging" in tokens
    assert "asyncio" in tokens
    assert "loop" in tokens


def test_tokenise_empty_input():
    assert _tokenise("") == set()
    assert _tokenise("a the of") == set()  # all stopwords


def test_tokenise_two_char_words_dropped():
    # min length 3 -> "go" survives only if first char fits the regex.
    assert "go" not in _tokenise("we go to")
    assert "git" in _tokenise("a git rebase")


# ---------- recommend_for_task -------------------------------------------------


def _make_skill(slug: str, name: str, when_to_use: str, body: str = "...") -> Skill:
    return Skill(
        slug=slug,
        name=name,
        when_to_use=when_to_use,
        version="1",
        body=body,
        source_file=Path(f"<{slug}>"),
        universal=False,
    )


class _FakeRegistry(SkillRegistry):
    def __init__(self, skills: list[Skill]) -> None:
        super().__init__()
        self._cache = {s.slug: s for s in skills}


def test_recommend_ranks_higher_overlap_first():
    reg = _FakeRegistry([
        _make_skill("debug", "Systematic debugging", "Use when investigating a bug or crash."),
        _make_skill("brainstorm", "Brainstorming", "Use when generating fresh ideas for a design."),
        _make_skill("plan", "Writing plans", "Use when planning a refactor or migration."),
    ])
    ranked = reg.recommend_for_task("Investigating a crash in asyncio")
    assert ranked[0][0].slug == "debug"
    assert ranked[0][1] > 0


def test_recommend_with_min_score_drops_zero_matches():
    reg = _FakeRegistry([
        _make_skill("debug", "Systematic debugging", "Use when investigating a bug or crash."),
        _make_skill("brainstorm", "Brainstorming", "Use when generating fresh ideas."),
    ])
    ranked = reg.recommend_for_task("Investigating a crash", min_score=0.05)
    assert all(score >= 0.05 for _, score in ranked)
    assert {s.slug for s, _ in ranked} == {"debug"}


def test_recommend_empty_task_returns_all_zero_score():
    reg = _FakeRegistry([
        _make_skill("a", "A", "use one"),
        _make_skill("b", "B", "use two"),
    ])
    ranked = reg.recommend_for_task("")
    assert {s.slug for s, _ in ranked} == {"a", "b"}
    assert all(score == 0.0 for _, score in ranked)


def test_recommend_ties_broken_by_slug():
    """Same score -> sorted by slug ascending."""
    reg = _FakeRegistry([
        _make_skill("zebra", "Z", "match keyword"),
        _make_skill("alpha", "A", "match keyword"),
    ])
    ranked = reg.recommend_for_task("match keyword")
    assert ranked[0][1] == ranked[1][1]
    assert ranked[0][0].slug == "alpha"


# ---------- composed_system_prompt_for_task -----------------------------------


def _make_universal(slug: str, when_to_use: str) -> Skill:
    return Skill(
        slug=slug,
        name=slug.replace("_", " ").title(),
        when_to_use=when_to_use,
        version="1",
        body=f"Body of {slug}",
        source_file=Path(f"<{slug}>"),
        universal=True,
    )


def _profile_with_universal_skills(skills: list[Skill]) -> ExpertProfile:
    reg = _FakeRegistry(skills)
    return ExpertProfile(
        name="test-expert",
        description="Test",
        source_file=Path("<test>"),
        data={"system_prompt": "ROLE_PROMPT", "uses_skills": []},
        skill_registry=reg,
    )


def test_task_filter_keeps_only_relevant_universals():
    skills = [
        _make_universal("debugging", "Use when debugging a crash or asyncio issue"),
        _make_universal("design", "Use when proposing an architecture change"),
    ]
    profile = _profile_with_universal_skills(skills)
    composed = profile.composed_system_prompt_for_task(
        "I need to debug a crash in asyncio",
        threshold=0.05,
    )
    assert "Body of debugging" in composed
    assert "Body of design" not in composed


def test_task_filter_threshold_zero_falls_back_to_unfiltered():
    skills = [_make_universal("debugging", "Use when debugging anything")]
    profile = _profile_with_universal_skills(skills)
    composed_filtered = profile.composed_system_prompt_for_task("anything", threshold=0.0)
    composed_full = profile.composed_system_prompt
    assert composed_filtered == composed_full


def test_task_filter_empty_task_falls_back_to_unfiltered():
    skills = [_make_universal("debugging", "Use when debugging anything")]
    profile = _profile_with_universal_skills(skills)
    composed_filtered = profile.composed_system_prompt_for_task("", threshold=0.5)
    composed_full = profile.composed_system_prompt
    assert composed_filtered == composed_full


def test_task_filter_keeps_declared_skills_regardless():
    """`uses_skills` is an explicit opt-in; task filter only touches universals."""
    universal = _make_universal("planning", "Use when planning a refactor")
    declared = _make_skill(
        "solid_dry", "SOLID/DRY", "Use for design discipline",
        body="DECLARED_BODY",
    )
    reg = _FakeRegistry([universal, declared])
    profile = ExpertProfile(
        name="test",
        description="",
        source_file=Path("<test>"),
        data={"system_prompt": "ROLE", "uses_skills": ["solid_dry"]},
        skill_registry=reg,
    )
    # Task is unrelated to any skill keyword -> universal dropped, declared kept.
    composed = profile.composed_system_prompt_for_task(
        "completely unrelated request",
        threshold=0.05,
    )
    assert "DECLARED_BODY" in composed
    assert "Body of planning" not in composed


def test_task_filter_does_not_break_role_prompt():
    skills = [_make_universal("anything", "use whenever")]
    profile = _profile_with_universal_skills(skills)
    composed = profile.composed_system_prompt_for_task("totally unrelated", threshold=0.5)
    assert "ROLE_PROMPT" in composed


# ---------- recommend_for_budget (cost-aware routing) -------------------------


def _make_skill_with_cost(slug, name, when_to_use, cost):
    return Skill(
        slug=slug, name=name, when_to_use=when_to_use, version="1",
        body="...", source_file=Path(f"<{slug}>"),
        universal=False, cost=cost,
    )


def test_recommend_for_budget_respects_total_cost():
    reg = _FakeRegistry([
        _make_skill_with_cost("a", "Apple", "fix bug crash", 2.0),
        _make_skill_with_cost("b", "Banana", "fix bug crash", 1.5),
        _make_skill_with_cost("c", "Cherry", "fix bug crash", 0.5),
    ])
    chosen = reg.recommend_for_budget("fix bug crash", budget=2.5)
    chosen_slugs = [s.slug for s, _ in chosen]
    chosen_total_cost = sum(s.cost for s, _ in chosen)
    assert chosen_total_cost <= 2.5
    # Greedy: highest-score-first, all three tie -> sort by slug ascending.
    # 'a' costs 2.0 (fits, spent=2.0), 'b' costs 1.5 (skipped, would exceed),
    # 'c' costs 0.5 (fits, spent=2.5). So chosen = [a, c].
    assert "a" in chosen_slugs
    assert "c" in chosen_slugs
    assert "b" not in chosen_slugs


def test_recommend_for_budget_skips_below_min_score():
    reg = _FakeRegistry([
        _make_skill_with_cost("relevant", "X", "fix crash bug", 1.0),
        _make_skill_with_cost("irrelevant", "Y", "make muffins", 0.5),
    ])
    chosen = reg.recommend_for_budget(
        "fix crash bug", budget=10.0, min_score=0.05,
    )
    chosen_slugs = {s.slug for s, _ in chosen}
    assert "relevant" in chosen_slugs
    assert "irrelevant" not in chosen_slugs


def test_recommend_for_budget_zero_budget_returns_empty():
    reg = _FakeRegistry([_make_skill_with_cost("a", "A", "fix bug", 1.0)])
    chosen = reg.recommend_for_budget("fix bug", budget=0.0)
    assert chosen == []


def test_recommend_for_budget_negative_raises():
    reg = _FakeRegistry([])
    with pytest.raises(ValueError, match=">= 0"):
        reg.recommend_for_budget("x", budget=-1.0)


def test_skill_default_cost_is_one():
    s = _make_skill("x", "X", "use it")
    assert s.cost == 1.0
