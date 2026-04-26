"""Tests for the shared keyword-overlap utilities."""

from __future__ import annotations

from swarm_core.textmatch import (
    STOPWORDS,
    jaccard_similarity,
    tokenise_keywords,
)


def test_tokenise_lowercases_and_filters():
    tokens = tokenise_keywords("Debug the AsyncIO Loop")
    assert tokens == {"debug", "asyncio", "loop"}


def test_tokenise_drops_stopwords():
    tokens = tokenise_keywords("use this when debugging the loop")
    assert "use" not in tokens
    assert "this" not in tokens
    assert "when" not in tokens
    assert "the" not in tokens
    assert "debugging" in tokens
    assert "loop" in tokens


def test_tokenise_min_length_3():
    tokens = tokenise_keywords("a go go git")
    assert "go" not in tokens
    assert "git" in tokens


def test_tokenise_empty():
    assert tokenise_keywords("") == set()
    assert tokenise_keywords("   ") == set()


def test_jaccard_basic():
    a = {"x", "y", "z"}
    b = {"y", "z", "w"}
    # intersection {y, z}, union {x, y, z, w} -> 2/4 = 0.5
    assert jaccard_similarity(a, b) == 0.5


def test_jaccard_identical_is_one():
    a = {"x", "y"}
    assert jaccard_similarity(a, a) == 1.0


def test_jaccard_empty_returns_zero():
    assert jaccard_similarity(set(), {"a"}) == 0.0
    assert jaccard_similarity({"a"}, set()) == 0.0
    assert jaccard_similarity(set(), set()) == 0.0


def test_stopwords_constant_includes_meta_words():
    # Spot-check the curated list: skill-vocabulary fillers must be in.
    for w in ("use", "this", "when", "the", "and"):
        assert w in STOPWORDS
