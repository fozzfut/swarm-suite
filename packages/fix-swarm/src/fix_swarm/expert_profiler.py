"""Fix-expert profile loading -- shim around `swarm_core.experts.ExpertRegistry`.

Historical note: this used to be a 145-line YAML loader with its own
finding-category-to-expert mapping. Both jobs are now done in
`swarm_core.experts` (registry + the `FindingMatchStrategy`
SuggestStrategy). The class below preserves the dict-shaped public
API so any future caller gets the same shape.

Currently no in-tree caller imports `FixExpertProfiler`; the
`suggest_experts` MCP tool in `server.py` has its own inline mapping.
The shim exists so external code (or a future server refactor) can
adopt swarm-core's strategy without re-introducing the duplication.
"""

from __future__ import annotations

from pathlib import Path

from swarm_core.experts import ExpertRegistry, FindingMatchStrategy
from swarm_core.experts.registry import ExpertProfile

_BUILTIN_DIR = Path(__file__).parent / "experts"


def _profile_to_dict(profile: ExpertProfile) -> dict:
    d = dict(profile.data)
    d.setdefault("name", profile.name)
    d.setdefault("description", profile.description)
    d["_source_file"] = str(profile.source_file)
    return d


def _suggestion_legacy_shape(suggestion: dict) -> dict:
    """`slug` -> `profile_name` to match the historical fix-swarm shape."""
    out = dict(suggestion)
    if "slug" in out and "profile_name" not in out:
        out["profile_name"] = out["slug"]
    return out


class FixExpertProfiler:
    """Backward-compatible facade over swarm_core's expert machinery."""

    def __init__(self, custom_dirs: list[Path] | None = None):
        self._reg = ExpertRegistry(
            builtin_dir=_BUILTIN_DIR,
            custom_dirs=custom_dirs or [],
            suggest_strategy=FindingMatchStrategy(),
        )

    def list_profiles(self) -> list[dict]:
        return [_profile_to_dict(p) for p in self._reg.list_profiles()]

    def load_profile(self, name: str) -> dict:
        try:
            profile = self._reg.load_profile(name)
        except FileNotFoundError as exc:
            raise FileNotFoundError(f"Fix expert profile '{name}' not found") from exc
        return _profile_to_dict(profile)

    def suggest_experts(self, findings: list[dict]) -> list[dict]:
        """Score fix-experts against a finding list (FindingMatchStrategy)."""
        suggestions = self._reg.suggest(findings)
        return [_suggestion_legacy_shape(s) for s in suggestions]
