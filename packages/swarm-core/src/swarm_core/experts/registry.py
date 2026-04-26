"""Expert YAML loading + caching + skill composition.

`ExpertRegistry` holds the discovered profiles; the `SuggestStrategy`
ranks them given context. `ExpertProfile.composed_system_prompt`
assembles the final prompt the AI client sees: the YAML's `system_prompt`
plus declared `uses_skills:` plus all universal skills (e.g. solid_dry,
karpathy_guidelines). See `swarm_core.skills` for the methodology
recipes and `docs/architecture/skill-composition.md` for the design.

The registry is intentionally permissive at load time -- a corrupt YAML
or a missing skill is logged as a warning and the rest continues. Hard
validation belongs to test-time linting (`tests/test_expert_yamls.py`),
not runtime.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Iterable

import yaml

from ..logging_setup import get_logger
from ..skills.registry import Skill, SkillRegistry, default_registry as _default_skill_registry
from .suggest import SuggestStrategy, NullSuggestStrategy

_log = get_logger("core.experts.registry")

# Backward-compat: callers that previously checked for the inline SOLID+DRY
# block should migrate to checking `composed_system_prompt`. The marker is
# still recognised so legacy YAMLs (with the block inlined) keep working
# during the migration period.
SOLID_DRY_BLOCK_MARKER = "## SOLID+DRY enforcement (apply to user code)"

# Minimum gap between composed sections so the prompt has clear visual
# breaks regardless of how the source files end (some YAMLs may end with
# trailing whitespace stripped, others with a final newline).
_SECTION_SEP = "\n\n---\n\n"


def compose_system_prompt(
    profile_dict: dict,
    *,
    source_file: Path | str = "<dict>",
    skill_registry: SkillRegistry | None = None,
) -> str:
    """Compose the prompt the AI agent should see, from a YAML-loaded dict.

    This is the surgical bridge for tools whose CLIs / orchestrators load
    YAML profiles into raw dicts. Replace:

        sys_prompt = profile.get("system_prompt", "")

    with:

        from swarm_core.experts import compose_system_prompt
        sys_prompt = compose_system_prompt(profile)

    Result includes the role's `system_prompt` plus every skill declared
    in `uses_skills:` plus every universal skill (solid_dry,
    karpathy_guidelines), de-duplicated. Equivalent to building an
    `ExpertProfile` and reading `.composed_system_prompt`, but without
    the dataclass dance.
    """
    profile = ExpertProfile(
        name=profile_dict.get("name", "unknown"),
        description=profile_dict.get("description", ""),
        source_file=Path(source_file) if not isinstance(source_file, Path) else source_file,
        data=profile_dict,
        skill_registry=skill_registry or _default_skill_registry,
    )
    return profile.composed_system_prompt


@dataclass
class ExpertProfile:
    """Parsed expert profile.

    `data` is the full YAML dict (forward-compatible: tools may read
    extra keys via `data.get("...")`).
    """

    name: str
    description: str
    source_file: Path
    data: dict = field(default_factory=dict)
    # Skill registry is injected so tests can swap in a fixture-loaded one.
    # Defaults to the package-level singleton in swarm_core.skills.
    skill_registry: SkillRegistry = field(default_factory=lambda: _default_skill_registry)

    @property
    def slug(self) -> str:
        """File stem -- the canonical identifier used in tool calls."""
        return self.source_file.stem

    @property
    def system_prompt(self) -> str:
        return self.data.get("system_prompt", "")

    @property
    def uses_skills(self) -> list[str]:
        """Slugs declared in the YAML's `uses_skills:` list (in order).

        Universal skills (e.g. solid_dry, karpathy_guidelines) are NOT
        listed here -- they're auto-attached at compose time.
        """
        raw = self.data.get("uses_skills", []) or []
        if not isinstance(raw, list):
            _log.warning("Profile %s `uses_skills:` is not a list; ignoring", self.source_file)
            return []
        return [str(s) for s in raw]

    def has_solid_dry_block(self) -> bool:
        """True if the inline SOLID+DRY marker is present (legacy check).

        Migration target: `composed_system_prompt`. After SOLID+DRY moves
        to a universal skill (`solid_dry.md`), this property only matches
        YAMLs that still inline the block. Once migration completes, the
        inline marker should be absent and this property returns False --
        the block content arrives via composition instead.
        """
        return SOLID_DRY_BLOCK_MARKER in self.system_prompt

    @property
    def composed_system_prompt(self) -> str:
        """Full prompt as the AI client should see it.

        Order:
            1. expert.system_prompt              (role + role-specific checks)
            2. declared skills (in order)        (methodology overlays)
            3. universal skills (in load order)  (solid_dry, karpathy_guidelines, ...)

        Duplicates are de-duplicated by slug. If the YAML still contains the
        inline SOLID+DRY block AND `solid_dry` is universal, the universal
        copy is suppressed -- so legacy and migrated YAMLs both produce a
        sane prompt.
        """
        return self._compose(universal_filter=lambda _s: True)

    def composed_system_prompt_for_task(
        self,
        task: str,
        *,
        threshold: float = 0.05,
    ) -> str:
        """Same as composed_system_prompt, but universal skills are filtered.

        Universals attach only when their `name + when_to_use` text shares
        enough tokens with `task` (Jaccard similarity >= `threshold`).
        Skills declared in `uses_skills:` are always attached -- the
        expert's author opted in explicitly. Empty `task` falls back to
        the unfiltered prompt.

        `threshold` defaults to 0.05 (~one shared keyword in a small
        task). Tools that want stricter filtering can raise it; setting
        it to 0 makes the call equivalent to `composed_system_prompt`.
        """
        if not task or threshold <= 0.0:
            return self.composed_system_prompt

        # Skill is a (mutable) dataclass and not hashable; index by slug.
        scored: dict[str, float] = {
            s.slug: score
            for s, score in self.skill_registry.recommend_for_task(task)
        }

        def _accepts_universal(skill: Skill) -> bool:
            score = scored.get(skill.slug, 0.0)
            keep = score >= threshold
            if not keep:
                _log.debug(
                    "Profile %s task-filter dropped universal %r (score=%.3f < %.3f)",
                    self.source_file, skill.slug, score, threshold,
                )
            return keep

        return self._compose(universal_filter=_accepts_universal)

    def _compose(self, *, universal_filter) -> str:
        """Shared assembly path for the two composed_system_prompt variants."""
        sections: list[str] = []
        sp = self.system_prompt.rstrip()
        if sp:
            sections.append(sp)

        seen: set[str] = set()
        # Declared skills first (explicit takes precedence over universal).
        for slug in self.uses_skills:
            if slug in seen:
                continue
            try:
                skill = self.skill_registry.get(slug)
            except FileNotFoundError:
                _log.warning("Profile %s declares unknown skill %r; ignoring",
                             self.source_file, slug)
                continue
            seen.add(slug)
            sections.append(skill.compose_body())

        # Universal skills, suppressed where the filter rejects them or
        # where content is already inline.
        for skill in self.skill_registry.universal_skills():
            if skill.slug in seen:
                continue
            if skill.slug == "solid_dry" and self.has_solid_dry_block():
                # Legacy YAML still has the block inlined; don't duplicate.
                seen.add(skill.slug)
                continue
            if not universal_filter(skill):
                continue
            seen.add(skill.slug)
            sections.append(skill.compose_body())

        return _SECTION_SEP.join(sections)


class ExpertRegistry:
    """Loads YAML profiles from a builtin dir + optional custom dirs.

    Caches results until `reload()` is called. Loading is best-effort:
    a corrupt YAML logs a warning and is skipped; one bad file does not
    take down the registry.
    """

    def __init__(
        self,
        builtin_dir: Path,
        custom_dirs: Iterable[Path] = (),
        suggest_strategy: SuggestStrategy | None = None,
        skill_registry: SkillRegistry | None = None,
    ) -> None:
        self._builtin = Path(builtin_dir)
        self._custom = [Path(d) for d in custom_dirs]
        self._strategy = suggest_strategy or NullSuggestStrategy()
        self._skill_registry = skill_registry or _default_skill_registry
        self._cache: dict[str, ExpertProfile] | None = None

    def list_profiles(self) -> list[ExpertProfile]:
        return list(self._load().values())

    def load_profile(self, slug: str) -> ExpertProfile:
        cache = self._load()
        if slug not in cache:
            raise FileNotFoundError(f"Expert profile {slug!r} not found")
        return cache[slug]

    def suggest(self, context: object) -> list[dict]:
        """Delegate to the configured strategy."""
        return self._strategy.suggest(self.list_profiles(), context)

    def reload(self) -> None:
        self._cache = None

    # ------------------------------------------------------------ internals

    def _load(self) -> dict[str, ExpertProfile]:
        if self._cache is not None:
            return self._cache
        cache: dict[str, ExpertProfile] = {}
        for d in [self._builtin, *self._custom]:
            if not d.is_dir():
                continue
            for yaml_file in sorted(d.glob("*.yaml")):
                profile = self._load_one(yaml_file)
                if profile is None:
                    continue
                cache[profile.slug] = profile  # later dirs override earlier
        self._cache = cache
        return cache

    def _load_one(self, path: Path) -> ExpertProfile | None:
        try:
            data = yaml.safe_load(path.read_text(encoding="utf-8"))
        except (yaml.YAMLError, OSError) as exc:
            _log.warning("Skipping corrupt profile %s: %s", path, exc)
            return None
        if not isinstance(data, dict):
            _log.warning("Profile %s is not a dict, skipping", path)
            return None
        name = data.get("name") or path.stem
        return ExpertProfile(
            name=name,
            description=data.get("description", ""),
            source_file=path,
            data=data,
            skill_registry=self._skill_registry,
        )
