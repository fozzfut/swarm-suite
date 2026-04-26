"""Suggest strategies -- pluggable scoring of expert relevance.

OCP in practice: adding a new "given X, suggest experts" path means
adding a new SuggestStrategy subclass, never editing the registry.

Built-in strategies:
    NullSuggestStrategy      empty list (default for tools that don't suggest)
    ProjectScanStrategy      scans a filesystem path for imports/patterns
    FindingMatchStrategy     scores against a list of finding dicts
"""

from __future__ import annotations

import re
from abc import ABC, abstractmethod
from pathlib import Path
from typing import TYPE_CHECKING

from ..logging_setup import get_logger

if TYPE_CHECKING:
    from .registry import ExpertProfile

_log = get_logger("core.experts.suggest")


class SuggestStrategy(ABC):
    """Pure scoring function: profiles + context -> ranked suggestion list."""

    @abstractmethod
    def suggest(self, profiles: list["ExpertProfile"], context: object) -> list[dict]:
        ...


class NullSuggestStrategy(SuggestStrategy):
    """Returns an empty suggestion list. Use when a tool doesn't auto-suggest."""

    def suggest(self, profiles: list["ExpertProfile"], context: object) -> list[dict]:
        return []


# --------------------------------------------------------------------- project scan


_DEFAULT_SOURCE_EXTS = (
    "*.py", "*.js", "*.ts", "*.tsx", "*.jsx",
    "*.go", "*.rs", "*.java", "*.kt", "*.kts",
    "*.cs", "*.cpp", "*.c", "*.h", "*.hpp",
    "*.rb", "*.ex", "*.exs", "*.swift", "*.php",
)
_DEFAULT_SKIP_DIRS = frozenset({
    "node_modules", ".venv", "venv", "__pycache__", ".git",
    "target", "build", "dist", "vendor", "bin", "obj",
    ".mypy_cache", ".pytest_cache", ".tox",
    ".eggs", "site-packages", ".worktrees",
})
_IMPORT_TEMPLATES = (
    "import {imp}",
    "from {imp}",
    "require('{imp}'",
    'require("{imp}"',
    "require '{imp}'",
    'require "{imp}"',
    "use {imp}",
    '#include "{imp}"',
    '#include <{imp}>',
    "using {imp}",
)


class ProjectScanStrategy(SuggestStrategy):
    """Score profiles by scanning a project directory for imports/patterns.

    Context: a `str` or `Path` pointing at a project root. Profiles need
    a `relevance_signals: { imports: [...], patterns: [...] }` block.
    """

    def __init__(
        self,
        source_exts: tuple[str, ...] = _DEFAULT_SOURCE_EXTS,
        skip_dirs: frozenset[str] = _DEFAULT_SKIP_DIRS,
    ) -> None:
        self._exts = source_exts
        self._skip = skip_dirs

    def suggest(self, profiles: list["ExpertProfile"], context: object) -> list[dict]:
        if not isinstance(context, (str, Path)):
            raise TypeError(
                f"ProjectScanStrategy expects str or Path context, got {type(context).__name__}"
            )
        proj = Path(context)
        if not proj.is_dir():
            return []

        file_contents = self._collect(proj)
        if not file_contents:
            return []

        all_text = "\n".join(file_contents.values())
        has_tests = self._project_has_tests(proj)

        suggestions: list[dict] = []
        for profile in profiles:
            score = self._score(profile, file_contents, all_text, has_tests)
            if score > 0:
                suggestions.append({
                    "slug": profile.slug,
                    "name": profile.name,
                    "description": profile.description,
                    "confidence": min(score, 1.0),
                })
        suggestions.sort(key=lambda s: s["confidence"], reverse=True)
        return suggestions

    # ------------------------------------------------------------ internals

    def _collect(self, root: Path) -> dict[str, str]:
        out: dict[str, str] = {}
        for ext in self._exts:
            for f in root.rglob(ext):
                try:
                    rel = f.relative_to(root)
                except ValueError:
                    continue
                if any(part in self._skip for part in rel.parts):
                    continue
                try:
                    out[str(rel)] = f.read_text(encoding="utf-8", errors="ignore")
                except OSError as exc:
                    _log.warning("Skipping %s: %s", f, exc)
        return out

    @staticmethod
    def _project_has_tests(root: Path) -> bool:
        for sub in ("tests", "test", "spec"):
            d = root / sub
            if d.exists() and any(d.rglob("*")):
                return True
        return False

    def _score(
        self,
        profile: "ExpertProfile",
        file_contents: dict[str, str],
        all_text: str,
        has_tests: bool,
    ) -> float:
        signals = profile.data.get("relevance_signals", {}) or {}
        imports = signals.get("imports", []) or []
        patterns = signals.get("patterns", []) or []

        score = 0.0
        for imp in imports:
            for tmpl in _IMPORT_TEMPLATES:
                if tmpl.format(imp=imp) in all_text:
                    score += 0.3
                    break
        for pat in patterns:
            try:
                if re.search(pat, all_text):
                    score += 0.2
            except re.error:
                continue

        # Universal experts always have a baseline
        name_lower = profile.name.lower()
        if file_contents and any(
            kw in name_lower
            for kw in ("contract", "signature", "consistency", "dead code",
                       "dependency", "drift", "project context")
        ):
            score = max(score, 0.5)

        if "test" in name_lower and has_tests:
            score = max(score, 0.7)

        return score


# --------------------------------------------------------------------- finding match


_DEFAULT_FINDING_MAP: dict[str, str] = {
    "security": "security-fix",
    "injection": "security-fix",
    "auth": "security-fix",
    "xss": "security-fix",
    "csrf": "security-fix",
    "performance": "performance-fix",
    "n+1": "performance-fix",
    "blocking": "performance-fix",
    "quadratic": "performance-fix",
    "caching": "performance-fix",
    "type-safety": "type-fix",
    "type": "type-fix",
    "nullable": "type-fix",
    "cast": "type-fix",
    "error-handling": "error-handling-fix",
    "swallowed-error": "error-handling-fix",
    "broad-catch": "error-handling-fix",
    "exception": "error-handling-fix",
    "test": "test-fix",
    "assertion": "test-fix",
    "flaky": "test-fix",
    "mock": "test-fix",
    "dependency": "dependency-fix",
    "deprecated": "dependency-fix",
    "vulnerability": "dependency-fix",
    "version": "dependency-fix",
    "compatibility": "compatibility-fix",
    "compat": "compatibility-fix",
    "platform": "compatibility-fix",
    "consistency": "refactoring",
    "dead-code": "refactoring",
    "design": "refactoring",
    "duplication": "refactoring",
    "architecture": "refactoring",
    "coupling": "refactoring",
    "modularity": "refactoring",
    "srp": "refactoring",
    "dry": "refactoring",
}


class FindingMatchStrategy(SuggestStrategy):
    """Map a list of finding dicts to fix-experts.

    Context: `list[dict]` -- each dict at minimum has `category`,
    `tags`, `title` keys. Score = 0.2 per matching finding, capped at 1.0.
    """

    def __init__(self, mapping: dict[str, str] | None = None) -> None:
        self._map = dict(mapping) if mapping else dict(_DEFAULT_FINDING_MAP)

    def suggest(self, profiles: list["ExpertProfile"], context: object) -> list[dict]:
        if not isinstance(context, list):
            raise TypeError(
                f"FindingMatchStrategy expects list[dict] context, "
                f"got {type(context).__name__}"
            )
        scores: dict[str, float] = {}
        counts: dict[str, int] = {}

        for finding in context:
            if not isinstance(finding, dict):
                continue
            category = str(finding.get("category", "")).lower()
            tags = [str(t).lower() for t in finding.get("tags", [])]
            title = str(finding.get("title", "")).lower()

            matched: set[str] = set()
            for key, expert in self._map.items():
                if key in category or any(key in tag for tag in tags) or key in title:
                    matched.add(expert)
            if not matched:
                matched.add("refactoring")
            for expert in matched:
                scores[expert] = scores.get(expert, 0.0) + 0.2
                counts[expert] = counts.get(expert, 0) + 1

        out: list[dict] = []
        for profile in profiles:
            score = min(scores.get(profile.slug, 0.0), 1.0)
            if score > 0:
                out.append({
                    "slug": profile.slug,
                    "name": profile.name,
                    "description": profile.description,
                    "confidence": score,
                    "matching_findings": counts.get(profile.slug, 0),
                })
        out.sort(key=lambda s: s["confidence"], reverse=True)
        return out
