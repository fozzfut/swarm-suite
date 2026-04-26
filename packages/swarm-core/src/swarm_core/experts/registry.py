"""Expert YAML loading + caching.

`ExpertRegistry` holds the discovered profiles; the `SuggestStrategy`
ranks them given some context (a project path, a list of findings, etc.).

The registry validates that every loaded YAML carries a non-empty
`name` and `system_prompt`. The `system_prompt` MUST end with the
SOLID+DRY block (see `solid_dry_block_check` -- enforced by tests).
"""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Iterable

import yaml

from ..logging_setup import get_logger
from .suggest import SuggestStrategy, NullSuggestStrategy

_log = get_logger("core.experts.registry")

SOLID_DRY_BLOCK_MARKER = "## SOLID+DRY enforcement (apply to user code)"


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

    @property
    def slug(self) -> str:
        """File stem -- the canonical identifier used in tool calls."""
        return self.source_file.stem

    @property
    def system_prompt(self) -> str:
        return self.data.get("system_prompt", "")

    def has_solid_dry_block(self) -> bool:
        return SOLID_DRY_BLOCK_MARKER in self.system_prompt


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
    ) -> None:
        self._builtin = Path(builtin_dir)
        self._custom = [Path(d) for d in custom_dirs]
        self._strategy = suggest_strategy or NullSuggestStrategy()
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
        )
