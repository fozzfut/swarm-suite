"""Expert profile loading -- shim around `swarm_core.experts.ExpertRegistry`.

Historical note: this file used to be a 180-line YAML loader + relevance
scorer. Both jobs are now done in `swarm_core.experts` (registry + the
`ProjectScanStrategy` SuggestStrategy). This shim preserves the
dict-shaped public API that legacy callers (orchestrator,
session_manager, CLI, tests) rely on while delegating the actual work
to swarm-core.

DRY win: ~150 lines of duplication eliminated; one canonical YAML
loader for the whole suite.
"""

from __future__ import annotations

from pathlib import Path

from swarm_core.experts import ExpertRegistry, ProjectScanStrategy
from swarm_core.experts.registry import ExpertProfile

from .logging_config import get_logger

_log = get_logger("expert_profiler")
_BUILTIN_DIR = Path(__file__).parent / "experts"


def _profile_to_dict(profile: ExpertProfile) -> dict:
    """Convert an ExpertProfile dataclass into the legacy dict shape.

    Includes `_source_file` for callers that switch on the YAML stem
    (e.g. orchestrator.py mapping suggestions back to expert configs).
    """
    d = dict(profile.data)
    d.setdefault("name", profile.name)
    d.setdefault("description", profile.description)
    d["_source_file"] = str(profile.source_file)
    return d


def _suggestion_legacy_shape(suggestion: dict) -> dict:
    """Map swarm_core's `slug`-keyed suggestion to the legacy `profile_name` shape."""
    out = dict(suggestion)
    if "slug" in out and "profile_name" not in out:
        out["profile_name"] = out["slug"]
    return out


class ExpertProfiler:
    """Backward-compatible facade. Returns dicts, delegates to ExpertRegistry."""

    def __init__(self, custom_dirs: list[Path] | None = None):
        self._reg = ExpertRegistry(
            builtin_dir=_BUILTIN_DIR,
            custom_dirs=custom_dirs or [],
            suggest_strategy=ProjectScanStrategy(),
        )

    def list_profiles(self) -> list[dict]:
        return [_profile_to_dict(p) for p in self._reg.list_profiles()]

    def load_profile(self, name: str) -> dict:
        try:
            profile = self._reg.load_profile(name)
        except FileNotFoundError as exc:
            # Preserve the legacy error message shape callers test against
            raise FileNotFoundError(f"Expert profile '{name}' not found") from exc
        return _profile_to_dict(profile)

    def suggest_experts(self, project_path: str) -> list[dict]:
        suggestions = self._reg.suggest(project_path)
        return [_suggestion_legacy_shape(s) for s in suggestions]
