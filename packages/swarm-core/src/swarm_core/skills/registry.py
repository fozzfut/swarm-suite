"""SkillRegistry -- discovers and loads skill markdown files.

A `Skill` is a parsed markdown file with YAML frontmatter. Universal skills
(`universal: true`) are auto-attached to every expert by the composition
logic in `swarm_core.experts.registry.ExpertProfile.composed_system_prompt`.

Task-conditioned composition: `recommend_for_task(task)` ranks skills by
keyword overlap between the task description and each skill's
`when_to_use` + `name` field. ExpertProfile.composed_system_prompt_for_task
uses this to filter which universal skills attach -- so a small task
doesn't eat its prompt budget on irrelevant methodology overlays.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Iterable

import yaml

from ..logging_setup import get_logger
from ..textmatch import jaccard_similarity, tokenise_keywords

_log = get_logger("core.skills.registry")
_BUILTIN_DIR = Path(__file__).parent

# Frontmatter delimiter; same as Jekyll/Hugo/superpowers.
_FRONTMATTER_DELIM = "---"

# Re-exported under the historical private name so tests that imported
# `_tokenise` from this module keep working. New callers should import
# from swarm_core.textmatch directly.
_tokenise = tokenise_keywords


@dataclass
class Skill:
    """A loaded methodology recipe.

    `body` is the markdown after the frontmatter, with the per-skill
    "I'm using the X skill" announcement prepended (see `compose_body`)
    so every skill block in a composed prompt makes its presence visible.

    `cost` is a relative weight (default 1.0) used by cost-aware
    selection (`SkillRegistry.recommend_for_budget`). Larger numbers
    mean more expensive to attach -- in practice, longer body, more
    tokens, more reasoning overhead. Skills mark this in their YAML
    frontmatter as `cost: 2.5` or similar; absent means 1.0.
    """

    slug: str
    name: str
    when_to_use: str
    version: str
    body: str
    source_file: Path
    universal: bool = False
    attribution: str = ""
    cost: float = 1.0
    raw_frontmatter: dict = field(default_factory=dict)

    def compose_body(self) -> str:
        """Return the skill body as it should appear in a composed prompt.

        Prepends the announcement line so the AI explicitly knows which
        skill is in play (mirrors superpowers' "Announce at start" pattern).
        """
        announce = f"_(Active skill: **{self.name}** -- {self.when_to_use})_"
        attribution = f"\n\n_{self.attribution}_" if self.attribution else ""
        return f"{announce}\n\n{self.body.rstrip()}{attribution}"


class SkillRegistry:
    """Loads + caches skill markdown files from one or more directories.

    Built-in skills live next to this file (`swarm_core/skills/*.md`).
    Custom dirs (passed in `custom_dirs`) override built-ins by slug.
    """

    def __init__(
        self,
        builtin_dir: Path = _BUILTIN_DIR,
        custom_dirs: Iterable[Path] = (),
    ) -> None:
        self._builtin = Path(builtin_dir)
        self._custom = [Path(d) for d in custom_dirs]
        self._cache: dict[str, Skill] | None = None

    def list_skills(self) -> list[Skill]:
        return list(self._load().values())

    def get(self, slug: str) -> Skill:
        cache = self._load()
        if slug not in cache:
            raise FileNotFoundError(f"Skill {slug!r} not found in {self._search_dirs()}")
        return cache[slug]

    def universal_skills(self) -> list[Skill]:
        return [s for s in self._load().values() if s.universal]

    def recommend_for_budget(
        self,
        task: str,
        *,
        budget: float,
        min_score: float = 0.0,
    ) -> list[tuple["Skill", float]]:
        """Pick highest-relevance skills whose total cost fits the budget.

        Greedy: sort by score desc, accumulate while sum-of-costs <=
        budget. `budget` is in the same arbitrary units as Skill.cost
        (typically "1.0 per average skill"). Skills below `min_score`
        are dropped before selection.

        Returns the chosen (Skill, score) list in score-desc order.
        Useful for prompt-budget-constrained composition: callers pass
        a max budget that maps to "I can afford to attach ~3 skills".
        """
        if budget < 0:
            raise ValueError("budget must be >= 0")
        ranked = self.recommend_for_task(task, min_score=min_score)
        chosen: list[tuple[Skill, float]] = []
        spent = 0.0
        for skill, score in ranked:
            if spent + skill.cost > budget:
                continue
            chosen.append((skill, score))
            spent += skill.cost
        return chosen

    def recommend_for_task(
        self,
        task: str,
        *,
        min_score: float = 0.0,
    ) -> list[tuple["Skill", float]]:
        """Rank skills by Jaccard overlap of task tokens with skill metadata.

        Returns a list of (Skill, score) sorted by score desc. `score`
        is in [0.0, 1.0]; higher means stronger match. Skills below
        `min_score` are dropped.

        Match surface: each skill's `name + when_to_use` text. The body
        is intentionally NOT scored -- bodies are long and would dilute
        the signal. Empty `task` returns every skill at score=0.
        """
        if not task:
            return [(s, 0.0) for s in self._load().values()]
        task_tokens = tokenise_keywords(task)
        if not task_tokens:
            return [(s, 0.0) for s in self._load().values()]
        scored: list[tuple[Skill, float]] = []
        for skill in self._load().values():
            skill_tokens = tokenise_keywords(f"{skill.name} {skill.when_to_use}")
            if not skill_tokens:
                continue
            score = jaccard_similarity(task_tokens, skill_tokens)
            if score >= min_score:
                scored.append((skill, score))
        scored.sort(key=lambda kv: (-kv[1], kv[0].slug))
        return scored

    def reload(self) -> None:
        self._cache = None

    # ------------------------------------------------------------ internals

    def _search_dirs(self) -> list[Path]:
        return [self._builtin, *self._custom]

    def _load(self) -> dict[str, Skill]:
        if self._cache is not None:
            return self._cache
        cache: dict[str, Skill] = {}
        for d in self._search_dirs():
            if not d.is_dir():
                continue
            for md_file in sorted(d.glob("*.md")):
                if md_file.name == "SKILL_FORMAT.md":
                    continue  # spec doc, not a skill
                skill = self._load_one(md_file)
                if skill is not None:
                    cache[skill.slug] = skill  # later dirs override
        self._cache = cache
        return cache

    def _load_one(self, path: Path) -> Skill | None:
        try:
            text = path.read_text(encoding="utf-8")
        except OSError as exc:
            _log.warning("Skipping skill %s: %s", path, exc)
            return None

        frontmatter, body = _split_frontmatter(text)
        if frontmatter is None:
            _log.warning("Skill %s has no YAML frontmatter; skipping", path)
            return None

        try:
            meta = yaml.safe_load(frontmatter) or {}
        except yaml.YAMLError as exc:
            _log.warning("Skill %s frontmatter unparseable: %s", path, exc)
            return None
        if not isinstance(meta, dict):
            _log.warning("Skill %s frontmatter is not a mapping; skipping", path)
            return None

        slug = meta.get("slug") or path.stem
        if slug != path.stem:
            _log.warning(
                "Skill %s slug %r does not match filename stem; using filename",
                path, slug,
            )
            slug = path.stem

        for required in ("name", "when_to_use", "version"):
            if not meta.get(required):
                _log.warning("Skill %s missing required frontmatter field %r; skipping",
                             path, required)
                return None

        try:
            cost = float(meta.get("cost", 1.0))
        except (TypeError, ValueError):
            _log.warning(
                "Skill %s has non-numeric `cost`; defaulting to 1.0", path,
            )
            cost = 1.0
        if cost < 0:
            _log.warning(
                "Skill %s has negative `cost` %r; clamping to 0.0", path, cost,
            )
            cost = 0.0
        return Skill(
            slug=slug,
            name=meta["name"],
            when_to_use=meta["when_to_use"],
            version=str(meta["version"]),
            body=body.strip(),
            source_file=path,
            universal=bool(meta.get("universal", False)),
            attribution=meta.get("attribution", "") or "",
            cost=cost,
            raw_frontmatter=meta,
        )


def _split_frontmatter(text: str) -> tuple[str | None, str]:
    """Split `---\\nfrontmatter\\n---\\nbody` into (frontmatter, body).

    Returns (None, text) if the file has no frontmatter.
    """
    lines = text.splitlines(keepends=True)
    if not lines or lines[0].strip() != _FRONTMATTER_DELIM:
        return None, text
    end_idx = None
    for i in range(1, len(lines)):
        if lines[i].strip() == _FRONTMATTER_DELIM:
            end_idx = i
            break
    if end_idx is None:
        return None, text
    frontmatter = "".join(lines[1:end_idx])
    body = "".join(lines[end_idx + 1:])
    return frontmatter, body


# Module-level default; reused so we don't re-parse skill files on every load.
default_registry = SkillRegistry()
