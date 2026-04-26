"""Lightweight keyword-overlap utilities used by routing and skill recommendation.

Two consumers today:
  * `swarm_core.skills.registry.SkillRegistry.recommend_for_task` uses
    these to filter universal skills by relevance.
  * `swarm_core.experts.suggest.TaskSimilarityStrategy` uses them to
    rank expert profiles for a task description.

Intentionally dependency-free -- no embeddings, no ML libs. The match
is Jaccard over a tokenised + stoplist-filtered set. For small expert
catalogues (~50 profiles) and short task strings this gives stable,
explainable scores; if a project ever needs semantic matching, swap
the strategy out -- this module stays the cheap baseline.
"""

from __future__ import annotations

import re

# Tiny stoplist for matching tasks against profile metadata. Domain
# words ("debug", "refactor", "auth") are NOT here -- they're the
# signal we want.
STOPWORDS: frozenset[str] = frozenset({
    "a", "an", "the", "and", "or", "of", "to", "in", "on", "for", "is",
    "are", "be", "this", "that", "with", "as", "at", "by", "it", "from",
    "into", "out", "but", "not", "no", "do", "does", "did", "if", "then",
    "than", "so", "you", "your", "we", "our", "they", "them", "their",
    "i", "me", "my", "use", "uses", "used", "using", "when", "where",
    "what", "any", "all", "some",
})

# Lowercase ASCII words >= 3 chars survive. "go" is dropped, "git" stays.
_WORD_RE = re.compile(r"[a-z][a-z0-9_]{2,}")


def tokenise_keywords(text: str) -> set[str]:
    """Lowercase tokens >= 3 chars, minus stopwords. Empty string -> empty set."""
    if not text:
        return set()
    return {w for w in _WORD_RE.findall(text.lower()) if w not in STOPWORDS}


def jaccard_similarity(a: set[str], b: set[str]) -> float:
    """Standard Jaccard: |a & b| / |a | b|. Empty inputs -> 0.0."""
    if not a or not b:
        return 0.0
    inter = a & b
    union = a | b
    return len(inter) / len(union) if union else 0.0
