"""SkillRegistry -- discovers and loads skill markdown files.

A `Skill` is a parsed markdown file with YAML frontmatter. Universal skills
(`universal: true`) are auto-attached to every expert by the composition
logic in `swarm_core.experts.registry.ExpertProfile.composed_system_prompt`.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Iterable

import yaml

from ..logging_setup import get_logger

_log = get_logger("core.skills.registry")
_BUILTIN_DIR = Path(__file__).parent

# Frontmatter delimiter; same as Jekyll/Hugo/superpowers.
_FRONTMATTER_DELIM = "---"


@dataclass
class Skill:
    """A loaded methodology recipe.

    `body` is the markdown after the frontmatter, with the per-skill
    "I'm using the X skill" announcement prepended (see `compose_body`)
    so every skill block in a composed prompt makes its presence visible.
    """

    slug: str
    name: str
    when_to_use: str
    version: str
    body: str
    source_file: Path
    universal: bool = False
    attribution: str = ""
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

        return Skill(
            slug=slug,
            name=meta["name"],
            when_to_use=meta["when_to_use"],
            version=str(meta["version"]),
            body=body.strip(),
            source_file=path,
            universal=bool(meta.get("universal", False)),
            attribution=meta.get("attribution", "") or "",
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
